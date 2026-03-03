"""
Sentinel-2 service — Fetch imagery & compute NDVI via Microsoft Planetary Computer.

Uses pystac-client + planetary-computer for signed access to cloud-optimised GeoTIFFs.
"""

from __future__ import annotations

import io
from typing import List

import numpy as np
import matplotlib
matplotlib.use("Agg")  # headless backend
import matplotlib.pyplot as plt
from pystac_client import Client
import planetary_computer
import rasterio
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


# ─── Band loading helpers ────────────────────────────────────────
def _load_band(item, band_name: str, bbox: list[float]) -> tuple[np.ndarray, any]:
    """Read a single band cropped to *bbox* from a COG asset."""
    href = item.assets[band_name].href
    with rasterio.open(href) as src:
        projected_bbox = transform_bounds("EPSG:4326", src.crs, *bbox)
        window = from_bounds(*projected_bbox, src.transform)
        data = src.read(1, window=window).astype(np.float32)
        transform = src.window_transform(window)
    return data, transform


def _normalize(band: np.ndarray, percentile: int = 98) -> np.ndarray:
    valid = band[np.isfinite(band) & (band > 0)]
    if valid.size == 0:
        return np.zeros_like(band)
    vmin, vmax = np.percentile(valid, [2, percentile])
    return np.clip((band - vmin) / (vmax - vmin + 1e-6), 0, 1)


# ─── Public API ──────────────────────────────────────────────────
def search_items(bbox: list[float], date_range: str, max_items: int = 5):
    """Return a list of Sentinel-2 STAC items sorted by cloud cover."""
    catalog = _get_catalog()
    search = catalog.search(
        collections=[S2_COLLECTION],
        bbox=bbox,
        datetime=date_range,
        query={"eo:cloud_cover": {"lt": S2_MAX_CLOUD_COVER}},
        max_items=max_items,
    )
    return sorted(search.items(), key=lambda i: i.properties["eo:cloud_cover"])


def get_ndvi_stats(
    bbox: list[float] | None = None,
    date_range: str = "2024-04-01/2024-07-01",
) -> dict:
    """
    Compute NDVI summary statistics for the first cloud-free image
    in the given *bbox* and *date_range*.

    Returns dict with: mean, std, min, max, percentiles.
    """
    bbox = bbox or FRANCE_BBOX
    items = search_items(bbox, date_range)
    if not items:
        return {"error": "No cloud-free images found"}

    item = items[0]
    red, _ = _load_band(item, "B04", bbox)
    nir, _ = _load_band(item, "B08", bbox)
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
) -> io.BytesIO:
    """
    Build a composite PNG (Sentinel-2 RGB + CLMS crop type overlay)
    and return it as an in-memory bytes buffer.
    """
    items = search_items(bbox, date_range)
    if not items:
        # Return a blank placeholder
        buf = io.BytesIO()
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf

    item = items[0]
    red, _ = _load_band(item, "B04", bbox)
    green, _ = _load_band(item, "B03", bbox)
    blue, _ = _load_band(item, "B02", bbox)

    rgb = np.stack([_normalize(red), _normalize(green), _normalize(blue)], axis=-1)

    # Fetch aligned CLMS WMS overlay
    clms_rgba = get_crop_type_overlay(
        bbox=bbox, width=red.shape[1], height=red.shape[0]
    )

    # Composite via matplotlib
    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    ax.imshow(rgb, extent=bbox, aspect="auto")
    if clms_rgba is not None:
        ax.imshow(clms_rgba, extent=bbox, aspect="auto", alpha=0.45)
    ax.axis("off")
    fig.tight_layout(pad=0)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    return buf
