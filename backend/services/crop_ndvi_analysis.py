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
    # Rhône Valley default — observation window June–September 2025
    "4.67,44.71,4.97,45.01": {
        "bbox": [4.67, 44.71, 4.97, 45.01],
        "item_id": "bundled-demo",
        "date": "2025-07-15T00:00:00Z",
        "date_range": "2025-06-01/2025-09-01",
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
                # Jun-Sep baseline: (0.55+0.30+0.22+0.20)/4 = 0.318
                # 0.38 / 0.318 = 1.19 → above baseline (wheat already harvested,
                # 0.38 reflects good cover-crop or healthy stubble)
                "yield_index": 1.19,
                "yield_index_label": "Normal (off-season)",
                "ndvi_baseline_used": 0.318,
                "optimal_ndvi_range": [0.70, 0.85],
                "peak_months": [4, 5],
                "observation_note": "Wheat is harvested by July in Rhône Valley; summer NDVI reflects stubble, not crop health. For yield assessment, use April-May imagery.",
                "yield_prediction": {
                    "predicted_yield_t_ha": 6.98,
                    "target_year": 2025,
                    "anomaly_vs_5yr_pct": 19.0,
                    "method": "agreste_trend_plus_ndvi",
                    "confidence": 0.5,
                    "confidence_note": "Low confidence: observation is off-season for wheat; index inflated by post-harvest cover",
                    "explanation": "Based on Agreste data for Drôme, Isère, Ardèche; 5yr avg 5.86 t/ha; NDVI index 1.19 (summer off-season — wheat harvested by July, index reflects stubble not crop vigour)",
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
                # Jun-Sep baseline: (0.55+0.78+0.82+0.65)/4 = 0.70
                # 0.72 / 0.70 = 1.03 → slightly above average (peak season — meaningful)
                "yield_index": 1.03,
                "yield_index_label": "Above average",
                "ndvi_baseline_used": 0.70,
                "optimal_ndvi_range": [0.75, 0.90],
                "peak_months": [7, 8],
                "observation_note": "Summer is peak season for maize. NDVI of 0.72 is in the good range (optimal 0.75-0.90). Yield index is reliable.",
                "yield_prediction": {
                    "predicted_yield_t_ha": 9.92,
                    "target_year": 2025,
                    "anomaly_vs_5yr_pct": 3.0,
                    "method": "agreste_trend_plus_ndvi",
                    "confidence": 1.0,
                    "confidence_note": "High confidence: peak growing season observation",
                    "explanation": "Based on Agreste data for Drôme, Isère, Ardèche; 5yr avg 9.63 t/ha; NDVI index 1.03 during peak season (+3%)",
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
                # Jun-Sep baseline: (0.50+0.55+0.56+0.48)/4 = 0.5225
                # 0.51 / 0.5225 = 0.98 → near average (peak season — meaningful)
                "yield_index": 0.98,
                "yield_index_label": "Near average",
                "ndvi_baseline_used": 0.523,
                "optimal_ndvi_range": [0.50, 0.65],
                "peak_months": [7, 8],
                "observation_note": "Summer is peak season for grapevines. NDVI 0.51 is within optimal range (0.50-0.65). Note: vineyard NDVI is naturally lower than field crops due to inter-row bare soil.",
                "yield_prediction": {
                    "predicted_yield_t_ha": 7.35,
                    "target_year": 2025,
                    "anomaly_vs_5yr_pct": -2.0,
                    "method": "agreste_trend_plus_ndvi",
                    "confidence": 1.0,
                    "confidence_note": "High confidence: peak growing season observation",
                    "explanation": "Based on Agreste data for Drôme, Ardèche; 5yr avg 7.50 t/ha; NDVI index 0.98 during peak season (−2%)",
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
                # Jun-Sep baseline: (0.48+0.25+0.20+0.18)/4 = 0.278
                # 0.35 / 0.278 = 1.26 → above baseline (harvested, like wheat)
                "yield_index": 1.26,
                "yield_index_label": "Normal (off-season)",
                "ndvi_baseline_used": 0.278,
                "optimal_ndvi_range": [0.65, 0.80],
                "peak_months": [4, 5],
                "observation_note": "Barley/oats harvested by June-July. Summer NDVI reflects stubble, not crop health.",
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
                # Jun-Sep baseline: (0.60+0.50+0.48+0.50)/4 = 0.52
                # 0.58 / 0.52 = 1.12 → above average (grassland stays green)
                "yield_index": 1.12,
                "yield_index_label": "Above average",
                "ndvi_baseline_used": 0.52,
                "optimal_ndvi_range": [0.55, 0.75],
                "peak_months": [5, 6],
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
                # Jun-Sep baseline: (0.62+0.60+0.50+0.38)/4 = 0.525
                # 0.44 / 0.525 = 0.84 → below average (mixed group, varied phenology)
                "yield_index": 0.84,
                "yield_index_label": "Slightly low (off-season)",
                "ndvi_baseline_used": 0.525,
                "optimal_ndvi_range": [0.55, 0.80],
                "peak_months": [6, 7],
            },
        },
    },
}

# ─── Per-crop NDVI phenological profiles ─────────────────────────
# Each crop has different NDVI behaviour depending on the observation
# month.  The baseline must match the *observation window*, not just a
# single annual peak, otherwise wheat (harvested by July) looks
# permanently "below average" when observed in summer.
#
# Structure:
#   group → {
#       "peak_months": [m, …],        # months of maximum canopy cover
#       "peak_ndvi":  (lo, hi),        # healthy NDVI range during peak
#       "summer_ndvi": (lo, hi),       # expected range during Jun-Sep window
#       "baseline_by_month": {m: val}, # monthly reference baselines
#       "optimal_range": (lo, hi),     # optimal NDVI the crop *should* reach
#       "stress_threshold": float,     # below this → definite stress
#   }
#
# Sources: Copernicus HR-VPP phenology, JECAM validation sites, INRAE
# phenological calendars for France.

_CROP_NDVI_PROFILES: dict[str, dict] = {
    "wheat": {
        # Winter wheat: peaks Apr-May (stem elongation → heading)
        # By July the crop is harvested — low NDVI is NORMAL
        "peak_months": [4, 5],
        "peak_ndvi": (0.70, 0.85),
        "summer_ndvi": (0.20, 0.50),  # stubble / bare soil after harvest
        "baseline_by_month": {
            1: 0.25, 2: 0.30, 3: 0.50, 4: 0.72, 5: 0.78,
            6: 0.55, 7: 0.30, 8: 0.22, 9: 0.20, 10: 0.20, 11: 0.22, 12: 0.24,
        },
        "optimal_range": (0.70, 0.85),
        "stress_threshold": 0.55,   # during peak; summer lows don't count
    },
    "maize": {
        # Maize: peaks Jul-Aug (tasseling → grain fill)
        # Summer observation window captures the critical growth phase
        "peak_months": [7, 8],
        "peak_ndvi": (0.75, 0.90),
        "summer_ndvi": (0.65, 0.85),
        "baseline_by_month": {
            1: 0.10, 2: 0.10, 3: 0.12, 4: 0.15, 5: 0.30, 6: 0.55,
            7: 0.78, 8: 0.82, 9: 0.65, 10: 0.35, 11: 0.15, 12: 0.10,
        },
        "optimal_range": (0.75, 0.90),
        "stress_threshold": 0.55,
    },
    "grape": {
        # Vineyards: peaks Jul-Aug but row-planted → mixed signal with bare soil
        # Canopy NDVI is lower than field crops due to inter-row gaps
        "peak_months": [7, 8],
        "peak_ndvi": (0.45, 0.65),
        "summer_ndvi": (0.40, 0.65),
        "baseline_by_month": {
            1: 0.18, 2: 0.18, 3: 0.22, 4: 0.32, 5: 0.42, 6: 0.50,
            7: 0.55, 8: 0.56, 9: 0.48, 10: 0.35, 11: 0.22, 12: 0.18,
        },
        "optimal_range": (0.50, 0.65),
        "stress_threshold": 0.30,
    },
    "other_cereal": {
        # Barley / oats / rye: similar to wheat, slightly earlier maturity
        "peak_months": [4, 5],
        "peak_ndvi": (0.65, 0.80),
        "summer_ndvi": (0.18, 0.45),
        "baseline_by_month": {
            1: 0.22, 2: 0.28, 3: 0.48, 4: 0.68, 5: 0.72,
            6: 0.48, 7: 0.25, 8: 0.20, 9: 0.18, 10: 0.18, 11: 0.20, 12: 0.22,
        },
        "optimal_range": (0.65, 0.80),
        "stress_threshold": 0.50,
    },
    "grassland": {
        # Permanent + temporary grassland: stays green most of the year
        "peak_months": [5, 6],
        "peak_ndvi": (0.55, 0.75),
        "summer_ndvi": (0.40, 0.70),
        "baseline_by_month": {
            1: 0.30, 2: 0.32, 3: 0.42, 4: 0.55, 5: 0.62, 6: 0.60,
            7: 0.50, 8: 0.48, 9: 0.50, 10: 0.45, 11: 0.35, 12: 0.30,
        },
        "optimal_range": (0.55, 0.75),
        "stress_threshold": 0.30,
    },
    "other": {
        # Sunflower, rapeseed, vegetables — varied; use conservative defaults
        "peak_months": [6, 7],
        "peak_ndvi": (0.55, 0.80),
        "summer_ndvi": (0.35, 0.70),
        "baseline_by_month": {
            1: 0.18, 2: 0.20, 3: 0.30, 4: 0.45, 5: 0.55, 6: 0.62,
            7: 0.60, 8: 0.50, 9: 0.38, 10: 0.25, 11: 0.20, 12: 0.18,
        },
        "optimal_range": (0.55, 0.80),
        "stress_threshold": 0.30,
    },
}

# Keep the old flat dict for backward compat (used in _build_analysis)
_NDVI_BASELINES: dict[str, float] = {
    k: v["baseline_by_month"][7]  # July default for summer observation
    for k, v in _CROP_NDVI_PROFILES.items()
}


def _get_monthly_baseline(group: str, date_range: str) -> float:
    """
    Return the appropriate NDVI baseline for *group* given the observation
    *date_range*.  Averages the monthly baselines across all months in the
    observation window.
    """
    profile = _CROP_NDVI_PROFILES.get(group)
    if profile is None:
        return 0.50

    # Parse months from date_range like "2025-06-01/2025-09-01"
    try:
        parts = date_range.split("/")
        start_month = int(parts[0].split("-")[1])
        end_month = int(parts[-1].split("-")[1])
        months = list(range(start_month, end_month + 1))
        if not months:
            months = [7]  # fallback
    except Exception:
        months = [7]

    baselines = [profile["baseline_by_month"].get(m, 0.50) for m in months]
    return sum(baselines) / len(baselines)


def _yield_index_for_crop(
    group: str, ndvi_mean: float, date_range: str
) -> tuple[float | None, str]:
    """
    Compute a phenology-aware yield index for a crop group.

    Returns (yield_index, label_string).

    The index is the ratio of observed NDVI to the expected monthly
    baseline.  The label uses *crop-specific* thresholds because e.g.
    wheat post-harvest NDVI of 0.30 is normal, while for maize during
    peak season the same value would be catastrophic.
    """
    profile = _CROP_NDVI_PROFILES.get(group)
    if profile is None:
        return None, "N/A"

    baseline = _get_monthly_baseline(group, date_range)
    if baseline <= 0:
        return None, "N/A"

    raw_index = round(ndvi_mean / baseline, 2)

    # Determine whether the observation falls during peak or off-season
    try:
        parts = date_range.split("/")
        obs_months = set(range(
            int(parts[0].split("-")[1]),
            int(parts[-1].split("-")[1]) + 1,
        ))
    except Exception:
        obs_months = {7}

    peak_months = set(profile["peak_months"])
    is_peak_season = bool(obs_months & peak_months)

    # ── Crop-specific labelling ──────────────────────────────────
    opt_lo, opt_hi = profile["optimal_range"]
    stress_th = profile["stress_threshold"]

    if not is_peak_season:
        # Off-season: the NDVI ratio is less meaningful for yield
        # Still report the index, but label accordingly
        if raw_index >= 0.95:
            label = "Normal (off-season)"
        elif raw_index >= 0.80:
            label = "Slightly low (off-season)"
        else:
            label = "Low (off-season; may be post-harvest)"
    else:
        # Peak season: NDVI is directly informative
        if ndvi_mean >= opt_lo:
            if raw_index >= 1.08:
                label = "Well above average"
            elif raw_index >= 1.02:
                label = "Above average"
            else:
                label = "Near average (good canopy)"
        elif ndvi_mean >= stress_th:
            if raw_index >= 0.95:
                label = "Near average"
            elif raw_index >= 0.85:
                label = "Below average"
            else:
                label = "Well below average"
        else:
            label = "Severe stress"

    return raw_index, label


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

        # ── Phenology-aware yield index ──────────────────────────
        yield_idx, yield_label = _yield_index_for_crop(group, mean_val, date_range)

        # Also store the monthly baseline used so agent can reason about it
        monthly_baseline = round(_get_monthly_baseline(group, date_range), 3)
        profile = _CROP_NDVI_PROFILES.get(group, {})

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
            "yield_index_label": yield_label,
            "ndvi_baseline_used": monthly_baseline,
            "optimal_ndvi_range": list(profile.get("optimal_range", [])),
            "peak_months": profile.get("peak_months", []),
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
