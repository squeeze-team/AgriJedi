"""
FAOSTAT service — historical crop yield data for France.

Uses the FAOSTAT Bulk Download / API for production statistics.
For the hackathon demo we include a bundled historical dataset
with a fallback to the live API.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import requests

from config import CROP_CONFIG, COUNTRY_ISO3, FAOSTAT_AREA_CODE


# ─── Embedded historical wheat yield for France (ton/ha) ─────────
# Source: FAOSTAT QCL — included here for offline/demo resilience.
# Yield in tonnes per hectare (hg/ha ÷ 10000).
_BUNDLED_YIELDS: dict[str, dict[int, float]] = {
    "wheat": {
        2010: 7.01, 2011: 6.72, 2012: 7.29,
        2013: 7.26, 2014: 7.57, 2015: 7.70,
        2016: 5.39, 2017: 7.36, 2018: 6.83,
        2019: 7.55, 2020: 6.77, 2021: 7.09,
        2022: 7.32, 2023: 7.10,
    },
    "maize": {
        2010: 8.69, 2011: 9.78, 2012: 8.79,
        2013: 8.32, 2014: 9.96, 2015: 8.56,
        2016: 8.07, 2017: 9.67, 2018: 8.25,
        2019: 8.83, 2020: 8.48, 2021: 9.59,
        2022: 7.61, 2023: 9.15,
    },
}

FAOSTAT_API_BASE = (
    "https://fenixservices.fao.org/faostat/api/v1/en/data/QCL"
)


def _fetch_faostat_api(crop: str) -> Optional[pd.DataFrame]:
    """
    Attempt to pull yield data from the FAOSTAT REST API.
    Returns a DataFrame with columns [year, yield_ton_ha] or None.
    """
    cfg = CROP_CONFIG.get(crop)
    if cfg is None:
        return None

    params = {
        "area": FAOSTAT_AREA_CODE,
        "item": cfg["faostat_item_code"],
        "element": cfg["faostat_element_code"],
        "year": ",".join(str(y) for y in range(2000, 2025)),
        "show_codes": "true",
        "show_unit": "true",
        "show_flags": "true",
        "null_values": "false",
        "output_type": "objects",
    }

    try:
        resp = requests.get(FAOSTAT_API_BASE, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("data", [])
    except Exception as exc:
        print(f"[faostat] API call failed: {exc}")
        return None

    if not data:
        return None

    records = [
        {"year": int(d["Year"]), "yield_ton_ha": float(d["Value"]) / 10000}
        for d in data
        if d.get("Value") is not None
    ]
    return pd.DataFrame(records).sort_values("year").reset_index(drop=True)


def get_yield_history(crop: str = "wheat") -> pd.DataFrame:
    """
    Return a DataFrame of annual yield (ton/ha) for France.
    Tries FAOSTAT API first, falls back to bundled data.
    """
    df = _fetch_faostat_api(crop)
    if df is not None and not df.empty:
        return df

    # Fallback to bundled data
    bundled = _BUNDLED_YIELDS.get(crop, {})
    if not bundled:
        return pd.DataFrame(columns=["year", "yield_ton_ha"])

    return pd.DataFrame(
        [{"year": y, "yield_ton_ha": v} for y, v in sorted(bundled.items())]
    )


def compute_yield_features(crop: str = "wheat") -> dict:
    """
    Derive yield-based features for the prediction pipeline.

    Returns
    -------
    dict with keys: yield_lag_1, yield_5yr_avg, yield_anomaly_pct
    """
    df = get_yield_history(crop)
    if df.empty or len(df) < 2:
        return {
            "yield_lag_1": None,
            "yield_5yr_avg": None,
            "yield_anomaly_pct": None,
        }

    latest = df.iloc[-1]["yield_ton_ha"]
    lag1 = df.iloc[-2]["yield_ton_ha"] if len(df) >= 2 else latest

    avg5 = df["yield_ton_ha"].tail(5).mean()
    anomaly_pct = (latest - avg5) / (avg5 + 1e-6) * 100

    return {
        "yield_lag_1": round(float(lag1), 3),
        "yield_5yr_avg": round(float(avg5), 3),
        "yield_anomaly_pct": round(float(anomaly_pct), 2),
    }
