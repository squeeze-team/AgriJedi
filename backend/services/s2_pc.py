"""
Sentinel-2 service — Fetch imagery & compute NDVI via Microsoft Planetary Computer.

Uses pystac-client + planetary-computer for signed access to cloud-optimised GeoTIFFs.
"""

from __future__ import annotations

import io
import threading
from collections import OrderedDict
from typing import Any

import numpy as np
import matplotlib
matplotlib.use("Agg")  # headless backend
from pystac_client import Client
import planetary_computer
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import from_bounds
from rasterio.warp import transform_bounds
from PIL import Image

from config import (
    PLANETARY_COMPUTER_STAC,
    S2_COLLECTION,
    S2_MAX_CLOUD_COVER,
    FRANCE_BBOX,
)
from services.clms_wms import get_crop_type_overlay


# ─── Bundled NDVI statistics per crop (fallback when S2 unavailable) ──
# Keyed by crop name → list of yearly NDVI summaries during peak growing season.
_BUNDLED_NDVI: dict[str, list[dict]] = {
    "wheat": [
        {"year": 2020, "ndvi_mean": 0.62, "ndvi_std": 0.12, "ndvi_min": 0.15,
         "ndvi_max": 0.85, "ndvi_p25": 0.54, "ndvi_p75": 0.72},
        {"year": 2021, "ndvi_mean": 0.65, "ndvi_std": 0.11, "ndvi_min": 0.18,
         "ndvi_max": 0.87, "ndvi_p25": 0.57, "ndvi_p75": 0.74},
        {"year": 2022, "ndvi_mean": 0.64, "ndvi_std": 0.13, "ndvi_min": 0.14,
         "ndvi_max": 0.86, "ndvi_p25": 0.55, "ndvi_p75": 0.73},
        {"year": 2023, "ndvi_mean": 0.63, "ndvi_std": 0.12, "ndvi_min": 0.16,
         "ndvi_max": 0.84, "ndvi_p25": 0.54, "ndvi_p75": 0.72},
        {"year": 2024, "ndvi_mean": 0.61, "ndvi_std": 0.14, "ndvi_min": 0.12,
         "ndvi_max": 0.83, "ndvi_p25": 0.51, "ndvi_p75": 0.71},
        {"year": 2025, "ndvi_mean": 0.60, "ndvi_std": 0.13, "ndvi_min": 0.13,
         "ndvi_max": 0.82, "ndvi_p25": 0.50, "ndvi_p75": 0.70},
    ],
    "maize": [
        {"year": 2020, "ndvi_mean": 0.68, "ndvi_std": 0.10, "ndvi_min": 0.22,
         "ndvi_max": 0.89, "ndvi_p25": 0.61, "ndvi_p75": 0.77},
        {"year": 2021, "ndvi_mean": 0.72, "ndvi_std": 0.09, "ndvi_min": 0.25,
         "ndvi_max": 0.91, "ndvi_p25": 0.65, "ndvi_p75": 0.80},
        {"year": 2022, "ndvi_mean": 0.58, "ndvi_std": 0.15, "ndvi_min": 0.10,
         "ndvi_max": 0.82, "ndvi_p25": 0.48, "ndvi_p75": 0.69},
        {"year": 2023, "ndvi_mean": 0.70, "ndvi_std": 0.10, "ndvi_min": 0.20,
         "ndvi_max": 0.90, "ndvi_p25": 0.63, "ndvi_p75": 0.78},
        {"year": 2024, "ndvi_mean": 0.67, "ndvi_std": 0.12, "ndvi_min": 0.18,
         "ndvi_max": 0.87, "ndvi_p25": 0.59, "ndvi_p75": 0.76},
        {"year": 2025, "ndvi_mean": 0.69, "ndvi_std": 0.11, "ndvi_min": 0.19,
         "ndvi_max": 0.88, "ndvi_p25": 0.61, "ndvi_p75": 0.77},
    ],
    "grape": [
        {"year": 2020, "ndvi_mean": 0.48, "ndvi_std": 0.14, "ndvi_min": 0.08,
         "ndvi_max": 0.72, "ndvi_p25": 0.38, "ndvi_p75": 0.58},
        {"year": 2021, "ndvi_mean": 0.45, "ndvi_std": 0.15, "ndvi_min": 0.06,
         "ndvi_max": 0.70, "ndvi_p25": 0.35, "ndvi_p75": 0.56},
        {"year": 2022, "ndvi_mean": 0.50, "ndvi_std": 0.13, "ndvi_min": 0.10,
         "ndvi_max": 0.74, "ndvi_p25": 0.41, "ndvi_p75": 0.60},
        {"year": 2023, "ndvi_mean": 0.47, "ndvi_std": 0.14, "ndvi_min": 0.07,
         "ndvi_max": 0.71, "ndvi_p25": 0.37, "ndvi_p75": 0.57},
        {"year": 2024, "ndvi_mean": 0.49, "ndvi_std": 0.13, "ndvi_min": 0.09,
         "ndvi_max": 0.73, "ndvi_p25": 0.40, "ndvi_p75": 0.59},
        {"year": 2025, "ndvi_mean": 0.46, "ndvi_std": 0.14, "ndvi_min": 0.08,
         "ndvi_max": 0.71, "ndvi_p25": 0.36, "ndvi_p75": 0.57},
    ],
}


def _get_bundled_ndvi(crop: str = "wheat", date_range: str = "") -> dict:
    """Return the most recent bundled NDVI stats for *crop*, optionally
    matching the year from *date_range* (e.g. '2024-04-01/2024-07-01')."""
    series = _BUNDLED_NDVI.get(crop, _BUNDLED_NDVI["wheat"])

    # Try to extract year from date_range
    target_year = None
    if date_range:
        try:
            target_year = int(date_range[:4])
        except (ValueError, IndexError):
            pass

    if target_year:
        for entry in series:
            if entry["year"] == target_year:
                return {**entry, "item_id": f"bundled-{crop}-{target_year}", "date": f"{target_year}-06-15T00:00:00Z"}

    # Fallback to most recent
    entry = series[-1]
    return {**entry, "item_id": f"bundled-{crop}-{entry['year']}", "date": f"{entry['year']}-06-15T00:00:00Z"}


# ─── STAC catalogue (lazy singleton) ─────────────────────────────
_catalog = None


def _get_catalog():
    global _catalog
    if _catalog is None:
        _catalog = Client.open(
            PLANETARY_COMPUTER_STAC,
            modifier=planetary_computer.sign_inplace,
        )
    return _catalog


# ─── In-memory caches (thread-safe) ──────────────────────────────
_cache_lock = threading.Lock()
_stac_search_cache: OrderedDict[tuple, list] = OrderedDict()
_band_cache: OrderedDict[tuple, tuple[np.ndarray, Any]] = OrderedDict()
_visual_cache: OrderedDict[tuple, tuple[bytes, dict]] = OrderedDict()

_MAX_STAC_CACHE = 32
_MAX_BAND_CACHE = 96
_MAX_VISUAL_CACHE = 64


def _bbox_key(bbox: list[float]) -> tuple[float, float, float, float]:
    return tuple(round(float(v), 6) for v in bbox)  # stable key for tiny float diffs


def _trim_lru(cache: OrderedDict, max_items: int):
    while len(cache) > max_items:
        cache.popitem(last=False)


def _get_visual_cache(key: tuple) -> tuple[io.BytesIO, dict] | None:
    with _cache_lock:
        cached = _visual_cache.get(key)
        if cached is None:
            return None
        _visual_cache.move_to_end(key)
        png_bytes, meta = cached
    return io.BytesIO(png_bytes), dict(meta)


def _set_visual_cache(key: tuple, png_buffer: io.BytesIO, meta: dict):
    payload = png_buffer.getvalue()
    with _cache_lock:
        _visual_cache[key] = (payload, dict(meta))
        _visual_cache.move_to_end(key)
        _trim_lru(_visual_cache, _MAX_VISUAL_CACHE)


# ─── Band loading helpers ────────────────────────────────────────
def _load_band(
    item,
    band_name: str,
    bbox: list[float],
    out_h: int | None = None,
    out_w: int | None = None,
) -> tuple[np.ndarray, Any]:
    """Read a single band cropped to *bbox* from a COG asset."""
    href = item.assets[band_name].href
    with rasterio.open(href) as src:
        projected_bbox = transform_bounds("EPSG:4326", src.crs, *bbox)
        window = from_bounds(*projected_bbox, src.transform)
        read_kwargs: dict[str, Any] = {"window": window}
        if out_h and out_w:
            read_kwargs["out_shape"] = (1, out_h, out_w)
            read_kwargs["resampling"] = Resampling.bilinear
            # Preserve requested window footprint even when bbox touches tile edge.
            read_kwargs["boundless"] = True
            read_kwargs["fill_value"] = np.nan
        data = src.read(1, **read_kwargs).astype(np.float32)
        transform = src.window_transform(window)
    return data, transform


def _load_band_cached(
    item,
    band_name: str,
    bbox: list[float],
    out_h: int | None = None,
    out_w: int | None = None,
) -> tuple[np.ndarray, Any]:
    key = (item.id, band_name, _bbox_key(bbox), out_h, out_w)
    with _cache_lock:
        cached = _band_cache.get(key)
        if cached is not None:
            _band_cache.move_to_end(key)
            return cached

    band = _load_band(item, band_name, bbox, out_h=out_h, out_w=out_w)
    with _cache_lock:
        _band_cache[key] = band
        _band_cache.move_to_end(key)
        _trim_lru(_band_cache, _MAX_BAND_CACHE)
    return band


def _normalize(band: np.ndarray, percentile: int = 98) -> np.ndarray:
    valid = band[np.isfinite(band) & (band > 0)]
    if valid.size == 0:
        return np.zeros_like(band)
    vmin, vmax = np.percentile(valid, [2, percentile])
    return np.clip((band - vmin) / (vmax - vmin + 1e-6), 0, 1)


# ─── Public API ──────────────────────────────────────────────────
def search_items(bbox: list[float], date_range: str, max_items: int = 5):
    """Return STAC items sorted by bbox coverage first, then cloud cover."""
    catalog = _get_catalog()
    search = catalog.search(
        collections=[S2_COLLECTION],
        bbox=bbox,
        datetime=date_range,
        query={"eo:cloud_cover": {"lt": S2_MAX_CLOUD_COVER}},
        max_items=max_items,
    )
    items = list(search.items())

    def _bbox_intersection_ratio(query_bbox: list[float], item_bbox: list[float] | None) -> float:
        if not item_bbox or len(item_bbox) != 4:
            return 0.0
        q_w, q_s, q_e, q_n = query_bbox
        i_w, i_s, i_e, i_n = item_bbox
        inter_w = max(q_w, i_w)
        inter_s = max(q_s, i_s)
        inter_e = min(q_e, i_e)
        inter_n = min(q_n, i_n)
        if inter_e <= inter_w or inter_n <= inter_s:
            return 0.0
        inter_area = (inter_e - inter_w) * (inter_n - inter_s)
        query_area = max((q_e - q_w) * (q_n - q_s), 1e-12)
        return float(inter_area / query_area)

    scored = [
        (
            _bbox_intersection_ratio(bbox, getattr(item, "bbox", None)),
            float(item.properties.get("eo:cloud_cover", 100)),
            item,
        )
        for item in items
    ]
    scored.sort(key=lambda s: (-s[0], s[1]))

    # Avoid extreme stretching: drop items that barely intersect the query bbox.
    filtered = [item for ratio, _cloud, item in scored if ratio >= 0.35]
    if filtered:
        return filtered
    return [item for _ratio, _cloud, item in scored]


def get_ndvi_stats(
    bbox: list[float] | None = None,
    date_range: str = "2024-04-01/2024-07-01",
    crop: str = "wheat",
) -> dict:
    """
    Compute NDVI summary statistics for the first cloud-free image
    in the given *bbox* and *date_range*.

    Returns dict with: mean, std, min, max, percentiles.
    Falls back to bundled data when Planetary Computer is unreachable.
    """
    bbox = bbox or FRANCE_BBOX
    try:
        items = _search_items_cached(bbox, date_range)
    except Exception as exc:
        print(f"[s2_pc] Sentinel-2 search failed: {exc}")
        items = []

    if not items:
        return _get_bundled_ndvi(crop=crop, date_range=date_range)

    item = items[0]
    red, _ = _load_band_cached(item, "B04", bbox)
    nir, _ = _load_band_cached(item, "B08", bbox)
    ndvi = (nir - red) / (nir + red + 1e-6)

    valid = ndvi[np.isfinite(ndvi)]
    return {
        "item_id": item.id,
        "date": item.datetime.isoformat(),
        "ndvi_mean": float(np.mean(valid)),
        "ndvi_std": float(np.std(valid)),
        "ndvi_min": float(np.min(valid)),
        "ndvi_max": float(np.max(valid)),
        "ndvi_p25": float(np.percentile(valid, 25)),
        "ndvi_p75": float(np.percentile(valid, 75)),
    }


def get_s2_overlay_png(
    bbox: list[float],
    date_range: str,
    width: int = 512,
    height: int = 512,
    item: Any | None = None,
) -> io.BytesIO:
    """
    Build a composite PNG (Sentinel-2 RGB + CLMS crop type overlay)
    and return it as an in-memory bytes buffer.
    """
    if item is None:
        items = _search_items_cached(bbox, date_range)
        if not items:
            # Return a blank placeholder
            buf = io.BytesIO()
            img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            img.save(buf, format="PNG")
            buf.seek(0)
            return buf
        item = items[0]

    red, _ = _load_band_cached(item, "B04", bbox, out_h=height, out_w=width)
    green, _ = _load_band_cached(item, "B03", bbox, out_h=height, out_w=width)
    blue, _ = _load_band_cached(item, "B02", bbox, out_h=height, out_w=width)

    rgb = np.stack([_normalize(red), _normalize(green), _normalize(blue)], axis=-1)

    # Fetch aligned CLMS WMS overlay
    clms_rgba = get_crop_type_overlay(
        bbox=bbox, width=width, height=height
    )
    rgb_img = Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8), mode="RGB").convert("RGBA")
    if clms_rgba is not None:
        clms_uint8 = (np.clip(clms_rgba, 0, 1) * 255).astype(np.uint8)
        # Keep CLMS alpha from WMS but soften overlay strength.
        clms_uint8[:, :, 3] = (clms_uint8[:, :, 3].astype(np.float32) * 0.45).astype(np.uint8)
        overlay_img = Image.fromarray(clms_uint8, mode="RGBA")
        if overlay_img.size != rgb_img.size:
            overlay_img = overlay_img.resize(rgb_img.size, Image.LANCZOS)
        rgb_img.alpha_composite(overlay_img)

    if rgb_img.size != (width, height):
        rgb_img = rgb_img.resize((width, height), Image.LANCZOS)

    buf = io.BytesIO()
    rgb_img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


# ─── Satellite visualisation panel (multi-layer) ─────────────────
def _search_items_cached(
    bbox: list[float], date_range: str, max_items: int = 5
) -> list:
    key = (_bbox_key(bbox), date_range, max_items)
    with _cache_lock:
        cached = _stac_search_cache.get(key)
        if cached is not None:
            _stac_search_cache.move_to_end(key)
            return cached
    items = search_items(bbox, date_range, max_items)
    with _cache_lock:
        _stac_search_cache[key] = items
        _stac_search_cache.move_to_end(key)
        _trim_lru(_stac_search_cache, _MAX_STAC_CACHE)
    return items


def _array_to_png(
    arr_rgb: np.ndarray, target_w: int, target_h: int
) -> io.BytesIO:
    """Convert a (H, W, 3) float32 [0,1] array to a resized PNG buffer."""
    arr_uint8 = (np.clip(arr_rgb, 0, 1) * 255).astype(np.uint8)
    img = Image.fromarray(arr_uint8, mode="RGB")
    if img.size != (target_w, target_h):
        img = img.resize((target_w, target_h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _ndvi_to_png(
    arr_2d: np.ndarray, target_w: int, target_h: int
) -> io.BytesIO:
    """Render NDVI to RGB PNG using colormap only (no matplotlib figure/colorbar)."""
    arr = np.asarray(arr_2d, dtype=np.float32)
    arr = np.nan_to_num(arr, nan=-0.2, posinf=0.9, neginf=-0.2)
    norm = np.clip((arr - (-0.2)) / (0.9 - (-0.2)), 0, 1)
    rgb = (matplotlib.colormaps["RdYlGn"](norm)[..., :3] * 255).astype(np.uint8)
    img = Image.fromarray(rgb, mode="RGB")
    if img.size != (target_w, target_h):
        img = img.resize((target_w, target_h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _placeholder_png(
    width: int, height: int, text: str = "No data"
) -> io.BytesIO:
    """Return a simple grey placeholder PNG."""
    del text
    img = Image.new("RGB", (width, height), (240, 240, 240))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def get_satellite_visualization(
    bbox: list[float],
    date_range: str,
    vis_type: str = "rgb",
    width: int = 512,
    height: int = 512,
) -> tuple[io.BytesIO, dict]:
    """
    Generate a satellite visualisation PNG for the requested layer type.

    Parameters
    ----------
    bbox : [west, south, east, north]
    date_range : STAC datetime string, e.g. "2025-06-01/2025-09-01"
    vis_type : "rgb" | "false_color" | "ndvi" | "overlay"
    width, height : output pixel dimensions

    Returns
    -------
    (png_buffer, metadata_dict)
    """
    cache_key = (_bbox_key(bbox), date_range, vis_type, width, height)
    cached = _get_visual_cache(cache_key)
    if cached is not None:
        cached_buf, cached_meta = cached
        cached_meta["render_cache"] = "hit"
        return cached_buf, cached_meta

    meta: dict = {"item_id": None, "date": None, "cloud_cover": None}

    try:
        items = _search_items_cached(bbox, date_range)
    except Exception as exc:
        print(f"[s2_pc] STAC search failed: {exc}")
        return _placeholder_png(width, height, "Sentinel-2 search failed"), meta

    if not items:
        return _placeholder_png(width, height, "No cloud-free images found"), meta

    item = items[0]
    meta = {
        "item_id": item.id,
        "date": item.datetime.isoformat() if item.datetime else None,
        "cloud_cover": item.properties.get("eo:cloud_cover"),
        "render_cache": "miss",
    }

    try:
        if vis_type == "rgb":
            red, _ = _load_band_cached(item, "B04", bbox, out_h=height, out_w=width)
            green, _ = _load_band_cached(item, "B03", bbox, out_h=height, out_w=width)
            blue, _ = _load_band_cached(item, "B02", bbox, out_h=height, out_w=width)
            rgb = np.stack(
                [_normalize(red), _normalize(green), _normalize(blue)],
                axis=-1,
            )
            out = _array_to_png(rgb, width, height)
            _set_visual_cache(cache_key, out, meta)
            return out, meta

        elif vis_type == "false_color":
            nir, _ = _load_band_cached(item, "B08", bbox, out_h=height, out_w=width)
            red, _ = _load_band_cached(item, "B04", bbox, out_h=height, out_w=width)
            green, _ = _load_band_cached(item, "B03", bbox, out_h=height, out_w=width)
            fc = np.stack(
                [_normalize(nir), _normalize(red), _normalize(green)],
                axis=-1,
            )
            out = _array_to_png(fc, width, height)
            _set_visual_cache(cache_key, out, meta)
            return out, meta

        elif vis_type == "ndvi":
            red, _ = _load_band_cached(item, "B04", bbox, out_h=height, out_w=width)
            nir, _ = _load_band_cached(item, "B08", bbox, out_h=height, out_w=width)
            ndvi = (nir - red) / (nir + red + 1e-6)
            out = _ndvi_to_png(ndvi, width, height)
            _set_visual_cache(cache_key, out, meta)
            return out, meta

        elif vis_type == "overlay":
            out = get_s2_overlay_png(bbox, date_range, width, height, item=item)
            _set_visual_cache(cache_key, out, meta)
            return out, meta

        else:
            return _placeholder_png(width, height, f"Unknown: {vis_type}"), meta

    except Exception as exc:
        print(f"[s2_pc] Visualisation error ({vis_type}): {exc}")
        return _placeholder_png(width, height, f"Error: {vis_type}\n{exc}"), meta
