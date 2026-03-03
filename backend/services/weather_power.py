"""
NASA POWER weather service — daily & monthly aggregated climate data.

Samples a 3×3 grid across France and aggregates to national averages.
Variables: PRECTOTCORR, T2M, T2M_MAX
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import requests

from config import NASA_POWER_BASE, POWER_PARAMETERS, FRANCE_WEATHER_GRID


def _fetch_power_point(
    lat: float, lon: float, start: str, end: str
) -> dict[str, Any] | None:
    """
    Call NASA POWER daily API for a single point.

    Parameters
    ----------
    lat, lon : coordinates
    start, end : date strings in yyyyMMdd format (e.g. "20230101")

    Returns
    -------
    dict  keyed by parameter name → {date_str: value, …} or None on error.
    """
    params = {
        "parameters": ",".join(POWER_PARAMETERS),
        "community": "AG",
        "longitude": lon,
        "latitude": lat,
        "start": start,
        "end": end,
        "format": "JSON",
    }

    try:
        resp = requests.get(NASA_POWER_BASE, params=params, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data.get("properties", {}).get("parameter", {})
    except requests.RequestException as exc:
        print(f"[weather_power] Request failed for ({lat},{lon}): {exc}")
        return None


def get_weather_daily(start_date: str, end_date: str) -> pd.DataFrame:
    """
    Fetch daily weather for the full France grid and return
    a DataFrame with columns: date, PRECTOTCORR, T2M, T2M_MAX
    (national-average across all grid points).
    """
    all_frames: list[pd.DataFrame] = []

    for lat, lon in FRANCE_WEATHER_GRID:
        raw = _fetch_power_point(lat, lon, start_date, end_date)
        if raw is None:
            continue

        # Each param is {date_str: value}
        records: dict[str, dict] = {}
        for param in POWER_PARAMETERS:
            series = raw.get(param, {})
            for date_str, val in series.items():
                records.setdefault(date_str, {})[param] = val

        df = pd.DataFrame.from_dict(records, orient="index")
        df.index.name = "date"
        df.index = pd.to_datetime(df.index, format="%Y%m%d")
        all_frames.append(df)

    if not all_frames:
        return pd.DataFrame()

    # Average across all grid points
    combined = pd.concat(all_frames).groupby(level=0).mean()
    combined.sort_index(inplace=True)
    return combined


def get_weather_monthly(start_date: str, end_date: str) -> dict:
    """
    Return monthly-aggregated weather as a JSON-friendly dict.

    Keys: months (list of "YYYY-MM"), and one list per parameter.
    """
    daily = get_weather_daily(start_date, end_date)
    if daily.empty:
        return {"months": [], "PRECTOTCORR": [], "T2M": [], "T2M_MAX": []}

    # Replace NASA fill values (-999) with NaN
    daily = daily.replace(-999, float("nan"))

    monthly = daily.resample("MS").agg(
        {
            "PRECTOTCORR": "sum",   # total monthly precipitation
            "T2M": "mean",          # mean temperature
            "T2M_MAX": "max",       # peak temperature (heatwave proxy)
        }
    )

    return {
        "months": monthly.index.strftime("%Y-%m").tolist(),
        "PRECTOTCORR": monthly["PRECTOTCORR"].round(2).tolist(),
        "T2M": monthly["T2M"].round(2).tolist(),
        "T2M_MAX": monthly["T2M_MAX"].round(2).tolist(),
    }


def compute_weather_features(start_date: str, end_date: str) -> dict:
    """
    Derive weather features for the feature engineering pipeline.

    Returns
    -------
    dict with keys: rain_last_12m, temp_mean_last_12m, heatwave_days,
                    drought_proxy  (rain anomaly estimate)
    """
    daily = get_weather_daily(start_date, end_date)
    if daily.empty:
        return {
            "rain_last_12m": None,
            "temp_mean_last_12m": None,
            "heatwave_days": None,
            "drought_proxy": None,
        }

    daily = daily.replace(-999, float("nan"))

    rain_total = daily["PRECTOTCORR"].sum()
    temp_mean = daily["T2M"].mean()

    # Heatwave: days where T2M_MAX > 35 °C  (simple threshold)
    heatwave_days = int((daily["T2M_MAX"] > 35).sum())

    # Drought proxy: percentage deviation from a rough long-term mean
    # (800 mm average annual precipitation for France — simplification)
    expected_rain = 800.0 * (len(daily) / 365.0)
    drought_proxy = (rain_total - expected_rain) / (expected_rain + 1e-6)

    return {
        "rain_last_12m": round(float(rain_total), 2),
        "temp_mean_last_12m": round(float(temp_mean), 2),
        "heatwave_days": heatwave_days,
        "drought_proxy": round(float(drought_proxy), 4),
    }
