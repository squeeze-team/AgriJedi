"""
Feature engineering — Build a unified feature vector from all data sources.

Combines weather, vegetation, yield, and price features into a single dict
that can be fed directly into the prediction models.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from config import CROP_CONFIG, FRANCE_BBOX
from services.weather_power import compute_weather_features
from services.faostat import compute_yield_features
from services.prices_worldbank import compute_price_features
from services.s2_pc import get_ndvi_stats


def _date_range_last_12m() -> tuple[str, str]:
    """Return (start, end) date strings for the last 12 months in yyyyMMdd format."""
    end = datetime.utcnow()
    start = end - timedelta(days=365)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _growing_season_date_range(crop: str) -> str:
    """Return a STAC-compatible date range string for the crop's peak NDVI months."""
    cfg = CROP_CONFIG.get(crop, CROP_CONFIG["wheat"])
    peak_months = cfg.get("ndvi_peak_months", [4, 5, 6])
    year = datetime.utcnow().year - 1  # use last completed growing season
    start_month = min(peak_months)
    end_month = max(peak_months)
    return f"{year}-{start_month:02d}-01/{year}-{end_month:02d}-28"


def build_feature_vector(
    crop: str = "wheat",
    country: str = "France",
    bbox: list[float] | None = None,
) -> dict:
    """
    Assemble the full feature vector for yield/price prediction.

    The returned dict contains:
      - Weather features  (rain_last_12m, temp_mean_last_12m, heatwave_days, drought_proxy)
      - Vegetation features  (ndvi_mean, ndvi_std, ndvi_anomaly — simplified)
      - Yield features  (yield_lag_1, yield_5yr_avg, yield_anomaly_pct)
      - Price features  (price_lag_1, price_lag_3, price_volatility)
    """
    bbox = bbox or FRANCE_BBOX
    start_date, end_date = _date_range_last_12m()

    # ── Weather ──────────────────────────────────────────────────
    weather = compute_weather_features(start_date, end_date)

    # ── Vegetation (NDVI) ────────────────────────────────────────
    try:
        ndvi_range = _growing_season_date_range(crop)
        ndvi_stats = get_ndvi_stats(bbox=bbox, date_range=ndvi_range)
    except Exception as exc:
        print(f"[build_features] NDVI fetch failed: {exc}")
        ndvi_stats = {}

    vegetation = {
        "ndvi_peak": ndvi_stats.get("ndvi_max"),
        "ndvi_mean": ndvi_stats.get("ndvi_mean"),
        "ndvi_std": ndvi_stats.get("ndvi_std"),
        # Simplified anomaly: difference from a typical good-season mean of 0.65
        "ndvi_anomaly_vs_avg": (
            round(ndvi_stats["ndvi_mean"] - 0.65, 4)
            if ndvi_stats.get("ndvi_mean") is not None
            else None
        ),
    }

    # ── Yield history ────────────────────────────────────────────
    yield_feat = compute_yield_features(crop)

    # ── Price history ────────────────────────────────────────────
    price_feat = compute_price_features(crop)

    # ── Combine ──────────────────────────────────────────────────
    features = {
        **weather,
        **vegetation,
        **yield_feat,
        **price_feat,
    }

    return features
