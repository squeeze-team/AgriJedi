"""
CLMS WMS service — Copernicus Land Monitoring Service (HRL Croplands Crop Types).

Provides crop-type map overlays via WMS GetMap and legend via GetLegendGraphic.
"""

from __future__ import annotations

import io
from typing import Optional

import numpy as np
import requests
from PIL import Image

from config import CLMS_WMS_URL, CLMS_LAYER_TEMPLATE, CLMS_DEFAULT_YEAR


def get_crop_type_overlay(
    bbox: list[float],
    width: int,
    height: int,
    year: int = CLMS_DEFAULT_YEAR,
    timeout: int = 60,
) -> Optional[np.ndarray]:
    """
    Fetch a crop-type PNG overlay from the CLMS WMS aligned to *bbox*.

    Parameters
    ----------
    bbox : [west, south, east, north] in EPSG:4326
    width, height : pixel dimensions matching the base image
    year : CLMS crop types reference year (default 2021)

    Returns
    -------
    np.ndarray of shape (H, W, 4) float32 in [0, 1] (RGBA), or None on error.
    """
    layer = CLMS_LAYER_TEMPLATE.format(year=year)
    west, south, east, north = bbox

    # WMS 1.3.0 + EPSG:4326: bbox order is lat/lon → minLat,minLon,maxLat,maxLon
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
        "transparent": "true",
    }

    try:
        resp = requests.get(CLMS_WMS_URL, params=params, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[clms_wms] WMS request failed: {exc}")
        return None

    img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
    arr = np.asarray(img, dtype=np.float32) / 255.0
    return arr


def get_legend_url(year: int = CLMS_DEFAULT_YEAR) -> str:
    """Return the WMS GetLegendGraphic URL for the crop types layer."""
    layer = CLMS_LAYER_TEMPLATE.format(year=year)
    return (
        f"{CLMS_WMS_URL}?service=WMS&request=GetLegendGraphic"
        f"&version=1.3.0&format=image/png&layer={layer}"
    )
