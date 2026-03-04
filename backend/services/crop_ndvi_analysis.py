"""
Crop-level NDVI analysis — per-crop yield proxy from colour-reverse-lookup.

Pipeline:
  1. Fetch CLMS WMS Crop Types PNG → decode RGB to crop class via colour table
  2. Fetch Sentinel-2 bands → compute NDVI matrix at matching bbox / resolution
  3. Mask NDVI per crop class → per-crop NDVI statistics
  4. Produce a relative yield proxy per crop

The colour → class mapping comes from the official CLMS HRL Croplands
Crop Types 2021 legend (CTY_S2021).

Reference legend (HRL CPL, 10 m):
  https://land.copernicus.eu/en/products/high-resolution-layer-crop-type
"""

from __future__ import annotations

import io
from typing import Any

import numpy as np
from PIL import Image
import requests

from config import (
    CLMS_WMS_URL,
    CLMS_LAYER_TEMPLATE,
    CLMS_DEFAULT_YEAR,
    FRANCE_BBOX,
    USE_BUNDLED_DATA,
)

# ─── CLMS Crop Types 2021 — colour legend ────────────────────────
# Official RGB values from the CLMS layer style.
# Mapping: (R, G, B) → (class_code, label, simplified_group)
#
# The simplified_group maps fine-grained CLMS classes to the 3 crop
# categories supported in our CROP_CONFIG (wheat, maize, grape).
# Pixels that don't match any known colour are classified as "other".
#
# NOTE: colour matching uses Euclidean distance with a tolerance to
# handle JPEG / antialiasing artefacts in the WMS PNG response.

_CLMS_COLOUR_TABLE: list[tuple[tuple[int, int, int], int, str, str]] = [
    # (R, G, B), class_code, label, simplified_group
    # --- Cereals / arable ---
    ((255, 255,   0), 211, "Common wheat",            "wheat"),
    ((255, 255, 100), 212, "Durum wheat",             "wheat"),
    ((200, 200,   0), 213, "Barley",                  "other_cereal"),
    ((240, 200,   0), 214, "Rye",                     "other_cereal"),
    ((230, 210,  60), 215, "Oats",                    "other_cereal"),
    ((255, 180,   0), 216, "Maize",                   "maize"),
    ((210, 180,  60), 217, "Rice",                    "other_cereal"),
    ((200, 130,   0), 218, "Triticale",               "other_cereal"),
    ((180, 150,   0), 219, "Other cereals",           "other_cereal"),
    # --- Industrial / oil / protein crops ---
    ((255, 230, 130), 221, "Potatoes",                "other"),
    ((205, 245,  80), 222, "Sugar beet",              "other"),
    ((240, 210, 120), 223, "Sunflower",               "other"),
    ((255, 190, 130), 224, "Rapeseed / canola",       "other"),
    ((180, 220,  90), 230, "Soya",                    "other"),
    ((130, 160,  70), 231, "Dry pulses",              "other"),
    # --- Fodder / grassland under rotation ---
    ((170, 240, 100), 241, "Temporary grassland",     "grassland"),
    ((150, 200,  80), 242, "Permanent grassland",     "grassland"),
    ((100, 170,  70), 243, "Clover / legume fodder",  "grassland"),
    ((120, 200, 100), 244, "Maize (silage/fodder)",   "maize"),
    # --- Fruits / vines ---
    ((160,  40, 170), 250, "Vineyards",               "grape"),
    ((180,  60, 200), 251, "Orchards",                "other_fruit"),
    ((200, 100, 220), 252, "Olive groves",            "other_fruit"),
    # --- Vegetables / other ---
    ((220, 170, 150), 260, "Vegetables",              "other"),
    ((180, 140, 120), 261, "Flowers / nurseries",     "other"),
    # --- Non-crop (may appear) ---
    ((  0,   0,   0),   0, "No data / background",    "nodata"),
    ((255, 255, 255), 254, "Non-cropland / built-up", "nodata"),
    ((200, 200, 200), 253, "Fallow",                  "other"),
]

# Pre-compute numpy arrays for fast vectorised distance lookup
_CT_RGB = np.array([c[0] for c in _CLMS_COLOUR_TABLE], dtype=np.float32)     # (N, 3)
_CT_CODES = np.array([c[1] for c in _CLMS_COLOUR_TABLE], dtype=np.int32)     # (N,)
_CT_LABELS = [c[2] for c in _CLMS_COLOUR_TABLE]
_CT_GROUPS = [c[3] for c in _CLMS_COLOUR_TABLE]

# Groups we report on (mapped to CROP_CONFIG names)
REPORTABLE_GROUPS = {"wheat", "maize", "grape", "other_cereal", "grassland", "other_fruit", "other"}

# Colour-distance tolerance (Euclidean in 0-255 RGB space)
_COLOUR_TOLERANCE = 40.0


# ─── Colour → class classification ───────────────────────────────

def classify_pixels(rgb_array: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Classify an (H, W, 3) uint8 RGB array into crop class codes and group indices.

    Returns
    -------
    class_codes : (H, W) int32 — CLMS class codes (0 for unmatched)
    group_names : list[str] — per-pixel group name (flat, same length as H*W)
    """
    h, w = rgb_array.shape[:2]
    flat = rgb_array.reshape(-1, 3).astype(np.float32)  # (N_pixels, 3)

    # Euclidean distance from each pixel to each legend colour
    # Using broadcasting: flat[:, None, :] - _CT_RGB[None, :, :]  →  (N_pixels, N_classes, 3)
    diff = flat[:, None, :] - _CT_RGB[None, :, :]
    dists = np.sqrt((diff ** 2).sum(axis=2))             # (N_pixels, N_classes)

    best_idx = dists.argmin(axis=1)                       # (N_pixels,)
    best_dist = dists[np.arange(len(flat)), best_idx]     # (N_pixels,)

    # Apply tolerance: pixels too far from any legend colour → nodata
    codes = _CT_CODES[best_idx].copy()
    codes[best_dist > _COLOUR_TOLERANCE] = 0

    groups = [_CT_GROUPS[i] if best_dist[j] <= _COLOUR_TOLERANCE else "nodata"
              for j, i in enumerate(best_idx)]

    return codes.reshape(h, w), groups


# ─── Fetch CLMS PNG as raw RGB array ─────────────────────────────

def fetch_clms_rgb(
    bbox: list[float],
    width: int,
    height: int,
    year: int = CLMS_DEFAULT_YEAR,
    timeout: int = 60,
) -> np.ndarray | None:
    """
    Fetch CLMS WMS Crop Types as an (H, W, 3) uint8 RGB array.
    Returns None on failure.
    """
    layer = CLMS_LAYER_TEMPLATE.format(year=year)
    west, south, east, north = bbox
    bbox_wms = f"{south},{west},{north},{east}"

    params = {
        "service": "WMS",
        "request": "GetMap",
        "version": "1.3.0",
        "layers": layer,
        "styles": "",
        "crs": "EPSG:4326",
        "bbox": bbox_wms,
        "width": str(width),
        "height": str(height),
        "format": "image/png",
        "transparent": "false",  # solid background for colour matching
    }

    try:
        resp = requests.get(CLMS_WMS_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        return np.asarray(img)
    except Exception as exc:
        print(f"[crop_ndvi] CLMS WMS fetch failed: {exc}")
        return None


# ─── Compute NDVI matrix ─────────────────────────────────────────

def _compute_ndvi_matrix(
    bbox: list[float], date_range: str, target_h: int, target_w: int
) -> np.ndarray | None:
    """
    Compute an (H, W) NDVI array from Sentinel-2 for *bbox*.
    Resizes to (target_h, target_w) to match the CLMS grid.
    Returns None on failure.
    """
    from services.s2_pc import search_items, _load_band

    try:
        items = search_items(bbox, date_range)
    except Exception as exc:
        print(f"[crop_ndvi] S2 search failed: {exc}")
        return None

    if not items:
        return None

    item = items[0]
    try:
        red, _ = _load_band(item, "B04", bbox)
        nir, _ = _load_band(item, "B08", bbox)
    except Exception as exc:
        print(f"[crop_ndvi] Band load failed: {exc}")
        return None

    ndvi = (nir - red) / (nir + red + 1e-6)

    # Resize to match CLMS grid dimensions
    if ndvi.shape != (target_h, target_w):
        from PIL import Image as _Img
        ndvi_img = _Img.fromarray(ndvi.astype(np.float32))
        ndvi_img = ndvi_img.resize((target_w, target_h), _Img.LANCZOS)
        ndvi = np.array(ndvi_img, dtype=np.float32)

    return ndvi


# ─── Bundled / demo analysis results ─────────────────────────────

_BUNDLED_ANALYSIS: dict[str, dict] = {
    # Rhône Valley default
    "4.67,44.71,4.97,45.01": {
        "bbox": [4.67, 44.71, 4.97, 45.01],
        "item_id": "bundled-demo",
        "date": "2025-07-15T00:00:00Z",
        "resolution_px": "400x400",
        "total_classified_pixels": 160000,
        "crops": {
            "wheat": {
                "label": "Common wheat + Durum wheat",
                "pixel_count": 32480,
                "area_pct": 20.3,
                "ndvi_mean": 0.38,
                "ndvi_std": 0.14,
                "ndvi_median": 0.36,
                "ndvi_p25": 0.28,
                "ndvi_p75": 0.47,
                "yield_index": 0.85,
                "yield_index_label": "Below average",
                "yield_prediction": {
                    "predicted_yield_t_ha": 4.98,
                    "target_year": 2025,
                    "anomaly_vs_5yr_pct": -15.0,
                    "method": "agreste_trend_plus_ndvi",
                    "confidence": 1.0,
                    "explanation": "Based on Agreste data for Drôme, Isère, Ardèche; 5yr avg 5.86 t/ha; NDVI index 0.85 (−15%)",
                    "avg_5yr": 5.86,
                    "trend": 0.004,
                    "history": {"2020": 5.67, "2021": 5.95, "2022": 6.2, "2023": 5.59, "2024": 5.87},
                    "departements": ["Drôme", "Isère", "Ardèche"],
                },
            },
            "maize": {
                "label": "Grain maize + Silage maize",
                "pixel_count": 25600,
                "area_pct": 16.0,
                "ndvi_mean": 0.72,
                "ndvi_std": 0.09,
                "ndvi_median": 0.74,
                "ndvi_p25": 0.66,
                "ndvi_p75": 0.79,
                "yield_index": 1.05,
                "yield_index_label": "Above average",
                "yield_prediction": {
                    "predicted_yield_t_ha": 10.11,
                    "target_year": 2025,
                    "anomaly_vs_5yr_pct": 5.0,
                    "method": "agreste_trend_plus_ndvi",
                    "confidence": 1.0,
                    "explanation": "Based on Agreste data for Drôme, Isère, Ardèche; 5yr avg 9.63 t/ha; NDVI index 1.05 (+5%)",
                    "avg_5yr": 9.63,
                    "trend": 0.02,
                    "history": {"2020": 9.3, "2021": 9.5, "2022": 9.8, "2023": 9.9, "2024": 9.65},
                    "departements": ["Drôme", "Isère", "Ardèche"],
                },
            },
            "grape": {
                "label": "Vineyards",
                "pixel_count": 44800,
                "area_pct": 28.0,
                "ndvi_mean": 0.51,
                "ndvi_std": 0.12,
                "ndvi_median": 0.52,
                "ndvi_p25": 0.43,
                "ndvi_p75": 0.60,
                "yield_index": 0.95,
                "yield_index_label": "Near average",
                "yield_prediction": {
                    "predicted_yield_t_ha": 7.13,
                    "target_year": 2025,
                    "anomaly_vs_5yr_pct": -5.0,
                    "method": "agreste_trend_plus_ndvi",
                    "confidence": 1.0,
                    "explanation": "Based on Agreste data for Drôme, Ardèche; 5yr avg 7.50 t/ha; NDVI index 0.95 (−5%)",
                    "avg_5yr": 7.50,
                    "trend": -0.01,
                    "history": {"2020": 7.6, "2021": 7.8, "2022": 7.2, "2023": 7.5, "2024": 7.4},
                    "departements": ["Drôme", "Ardèche"],
                },
            },
            "other_cereal": {
                "label": "Barley, Oats, Rye, etc.",
                "pixel_count": 8000,
                "area_pct": 5.0,
                "ndvi_mean": 0.35,
                "ndvi_std": 0.15,
                "ndvi_median": 0.33,
                "ndvi_p25": 0.24,
                "ndvi_p75": 0.44,
                "yield_index": 0.80,
                "yield_index_label": "Below average",
            },
            "grassland": {
                "label": "Temporary + Permanent grassland",
                "pixel_count": 19200,
                "area_pct": 12.0,
                "ndvi_mean": 0.58,
                "ndvi_std": 0.11,
                "ndvi_median": 0.59,
                "ndvi_p25": 0.50,
                "ndvi_p75": 0.66,
                "yield_index": None,
                "yield_index_label": "N/A",
            },
            "other": {
                "label": "Sunflower, Rapeseed, Vegetables, etc.",
                "pixel_count": 11200,
                "area_pct": 7.0,
                "ndvi_mean": 0.44,
                "ndvi_std": 0.18,
                "ndvi_median": 0.42,
                "ndvi_p25": 0.30,
                "ndvi_p75": 0.56,
                "yield_index": None,
                "yield_index_label": "N/A",
            },
        },
    },
}

# Historical NDVI baselines per group for yield-index computation
# (5-year mean NDVI during peak growing season — simplified)
_NDVI_BASELINES: dict[str, float] = {
    "wheat": 0.45,
    "maize": 0.68,
    "grape": 0.53,
    "other_cereal": 0.43,
    "grassland": 0.55,
    "other_fruit": 0.50,
    "other": 0.45,
}


# ─── Main analysis function ──────────────────────────────────────

def _yield_index_label(idx: float | None) -> str:
    if idx is None:
        return "N/A"
    if idx >= 1.10:
        return "Well above average"
    if idx >= 1.02:
        return "Above average"
    if idx >= 0.98:
        return "Near average"
    if idx >= 0.90:
        return "Below average"
    return "Well below average"


def analyze_crop_ndvi(
    bbox: list[float],
    date_range: str = "2025-06-01/2025-09-01",
    resolution: int = 400,
) -> dict[str, Any]:
    """
    Full pipeline: CLMS colour → crop mask + Sentinel-2 NDVI → per-crop stats.

    Parameters
    ----------
    bbox : [west, south, east, north]
    date_range : Sentinel-2 date range
    resolution : pixel width and height for both CLMS and NDVI grids

    Returns
    -------
    JSON-friendly dict with per-crop NDVI stats and yield proxy.
    """
    bbox_key = ",".join(f"{v}" for v in bbox)

    # ── Try live data ────────────────────────────────────────────
    if not USE_BUNDLED_DATA:
        clms_rgb = fetch_clms_rgb(bbox, resolution, resolution)
        if clms_rgb is not None:
            ndvi = _compute_ndvi_matrix(bbox, date_range, resolution, resolution)
            if ndvi is not None:
                return _build_analysis(bbox, clms_rgb, ndvi, date_range)

    # ── Fallback to bundled ──────────────────────────────────────
    if bbox_key in _BUNDLED_ANALYSIS:
        return _BUNDLED_ANALYSIS[bbox_key]

    # ── Try live even in bundled mode (CLMS is usually reliable) ──
    try:
        clms_rgb = fetch_clms_rgb(bbox, resolution, resolution)
        if clms_rgb is not None:
            ndvi = _compute_ndvi_matrix(bbox, date_range, resolution, resolution)
            if ndvi is not None:
                return _build_analysis(bbox, clms_rgb, ndvi, date_range)
    except Exception as exc:
        print(f"[crop_ndvi] Live fallback failed: {exc}")

    # ── Last resort: generic bundled ─────────────────────────────
    return {
        "bbox": bbox,
        "item_id": None,
        "date": None,
        "resolution_px": f"{resolution}x{resolution}",
        "total_classified_pixels": 0,
        "error": "No data available for this region. Try Rhône Valley (4.67,44.71,4.97,45.01).",
        "crops": {},
    }


def _build_analysis(
    bbox: list[float],
    clms_rgb: np.ndarray,
    ndvi: np.ndarray,
    date_range: str,
) -> dict[str, Any]:
    """Assemble per-crop NDVI statistics from classified CLMS pixels + NDVI grid."""
    h, w = clms_rgb.shape[:2]
    class_codes, group_list = classify_pixels(clms_rgb)
    group_arr = np.array(group_list).reshape(h, w)

    total_valid = int((class_codes != 0).sum())
    crops_result: dict[str, dict] = {}

    for group in REPORTABLE_GROUPS:
        mask = group_arr == group
        count = int(mask.sum())
        if count == 0:
            continue

        ndvi_masked = ndvi[mask]
        ndvi_valid = ndvi_masked[np.isfinite(ndvi_masked)]

        if len(ndvi_valid) == 0:
            continue

        mean_val = float(np.mean(ndvi_valid))
        baseline = _NDVI_BASELINES.get(group, 0.50)
        yield_idx = round(mean_val / baseline, 2) if baseline > 0 else None

        # Find the label(s) for this group
        labels = sorted(set(
            ct[2] for ct in _CLMS_COLOUR_TABLE if ct[3] == group
        ))

        crops_result[group] = {
            "label": ", ".join(labels[:3]) + ("…" if len(labels) > 3 else ""),
            "pixel_count": count,
            "area_pct": round(count / max(total_valid, 1) * 100, 1),
            "ndvi_mean": round(mean_val, 3),
            "ndvi_std": round(float(np.std(ndvi_valid)), 3),
            "ndvi_median": round(float(np.median(ndvi_valid)), 3),
            "ndvi_p25": round(float(np.percentile(ndvi_valid, 25)), 3),
            "ndvi_p75": round(float(np.percentile(ndvi_valid, 75)), 3),
            "yield_index": yield_idx,
            "yield_index_label": _yield_index_label(yield_idx),
            "yield_prediction": None,  # filled below
        }

    # ── Agreste-based yield predictions for main crops ─────────
    from services.agreste import predict_yield_from_index

    for group in ("wheat", "maize", "grape"):
        if group not in crops_result:
            continue
        yield_idx = crops_result[group].get("yield_index")
        pred = predict_yield_from_index(bbox, group, yield_idx)
        if pred.get("predicted_yield_t_ha") is not None:
            crops_result[group]["yield_prediction"] = {
                "predicted_yield_t_ha": pred["predicted_yield_t_ha"],
                "target_year": pred.get("target_year"),
                "anomaly_vs_5yr_pct": pred.get("anomaly_vs_5yr_pct"),
                "method": pred.get("method"),
                "confidence": pred.get("confidence"),
                "explanation": pred.get("explanation"),
                "avg_5yr": pred.get("components", {}).get("avg_5yr_t_ha"),
                "trend": pred.get("components", {}).get("trend_t_ha_yr"),
                "history": pred.get("history"),
                "departements": [d.get("name", "") for d in pred.get("departements", [])],
            }

    return {
        "bbox": bbox,
        "item_id": "live",
        "date": date_range,
        "resolution_px": f"{w}x{h}",
        "total_classified_pixels": total_valid,
        "crops": crops_result,
    }
