"""
NASA POWER weather service — daily & monthly aggregated climate data.

Samples a 3×3 grid across France and aggregates to national averages.
Variables: PRECTOTCORR, T2M, T2M_MAX
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd
import requests

from config import NASA_POWER_BASE, POWER_PARAMETERS, FRANCE_WEATHER_GRID, USE_BUNDLED_DATA


# ─── Bundled monthly weather for France (national average) ───────
# Source: ERA5 / NASA POWER historical monthly estimates for demo resilience.
# PRECTOTCORR = total precip mm/month, T2M = mean temp °C, T2M_MAX = peak temp °C
_BUNDLED_WEATHER_MONTHLY: list[dict] = [
    {"month": "2023-01", "PRECTOTCORR": 62.3, "T2M": 5.1, "T2M_MAX": 12.4},
    {"month": "2023-02", "PRECTOTCORR": 38.7, "T2M": 6.3, "T2M_MAX": 14.8},
    {"month": "2023-03", "PRECTOTCORR": 55.1, "T2M": 9.2, "T2M_MAX": 18.6},
    {"month": "2023-04", "PRECTOTCORR": 72.4, "T2M": 11.8, "T2M_MAX": 22.1},
    {"month": "2023-05", "PRECTOTCORR": 65.0, "T2M": 15.0, "T2M_MAX": 26.3},
    {"month": "2023-06", "PRECTOTCORR": 42.8, "T2M": 20.5, "T2M_MAX": 33.7},
    {"month": "2023-07", "PRECTOTCORR": 35.2, "T2M": 22.1, "T2M_MAX": 36.5},
    {"month": "2023-08", "PRECTOTCORR": 48.6, "T2M": 21.8, "T2M_MAX": 35.8},
    {"month": "2023-09", "PRECTOTCORR": 58.3, "T2M": 18.9, "T2M_MAX": 30.2},
    {"month": "2023-10", "PRECTOTCORR": 80.5, "T2M": 14.7, "T2M_MAX": 23.4},
    {"month": "2023-11", "PRECTOTCORR": 75.2, "T2M": 8.5, "T2M_MAX": 15.6},
    {"month": "2023-12", "PRECTOTCORR": 70.8, "T2M": 5.8, "T2M_MAX": 12.0},
    {"month": "2024-01", "PRECTOTCORR": 58.0, "T2M": 4.8, "T2M_MAX": 11.2},
    {"month": "2024-02", "PRECTOTCORR": 45.5, "T2M": 6.9, "T2M_MAX": 15.3},
    {"month": "2024-03", "PRECTOTCORR": 50.2, "T2M": 9.8, "T2M_MAX": 19.1},
    {"month": "2024-04", "PRECTOTCORR": 68.7, "T2M": 12.5, "T2M_MAX": 23.5},
    {"month": "2024-05", "PRECTOTCORR": 78.3, "T2M": 15.9, "T2M_MAX": 27.0},
    {"month": "2024-06", "PRECTOTCORR": 38.1, "T2M": 19.8, "T2M_MAX": 32.5},
    {"month": "2024-07", "PRECTOTCORR": 28.5, "T2M": 23.2, "T2M_MAX": 37.8},
    {"month": "2024-08", "PRECTOTCORR": 32.0, "T2M": 22.5, "T2M_MAX": 36.2},
    {"month": "2024-09", "PRECTOTCORR": 52.4, "T2M": 18.2, "T2M_MAX": 29.5},
    {"month": "2024-10", "PRECTOTCORR": 72.8, "T2M": 13.4, "T2M_MAX": 22.0},
    {"month": "2024-11", "PRECTOTCORR": 68.5, "T2M": 7.9, "T2M_MAX": 14.8},
    {"month": "2024-12", "PRECTOTCORR": 74.2, "T2M": 5.2, "T2M_MAX": 11.5},
    {"month": "2025-01", "PRECTOTCORR": 55.8, "T2M": 4.5, "T2M_MAX": 10.8},
    {"month": "2025-02", "PRECTOTCORR": 42.0, "T2M": 5.9, "T2M_MAX": 13.5},
    {"month": "2025-03", "PRECTOTCORR": 60.1, "T2M": 8.7, "T2M_MAX": 17.9},
    {"month": "2025-04", "PRECTOTCORR": 70.5, "T2M": 11.4, "T2M_MAX": 21.8},
    {"month": "2025-05", "PRECTOTCORR": 62.0, "T2M": 14.8, "T2M_MAX": 25.5},
    {"month": "2025-06", "PRECTOTCORR": 40.2, "T2M": 19.5, "T2M_MAX": 31.8},
    {"month": "2025-07", "PRECTOTCORR": 30.5, "T2M": 22.8, "T2M_MAX": 37.2},
    {"month": "2025-08", "PRECTOTCORR": 35.8, "T2M": 21.9, "T2M_MAX": 35.5},
    {"month": "2025-09", "PRECTOTCORR": 55.0, "T2M": 17.8, "T2M_MAX": 28.8},
    {"month": "2025-10", "PRECTOTCORR": 76.0, "T2M": 13.0, "T2M_MAX": 21.5},
    {"month": "2025-11", "PRECTOTCORR": 72.5, "T2M": 8.0, "T2M_MAX": 15.2},
    {"month": "2025-12", "PRECTOTCORR": 68.0, "T2M": 5.5, "T2M_MAX": 11.8},
]


def _get_bundled_monthly(start_date: str, end_date: str) -> dict:
    """Return bundled monthly weather data filtered to the requested range."""
    import datetime
    start = datetime.datetime.strptime(start_date, "%Y%m%d")
    end = datetime.datetime.strptime(end_date, "%Y%m%d")

    months, precip, t2m, t2m_max = [], [], [], []
    for row in _BUNDLED_WEATHER_MONTHLY:
        dt = datetime.datetime.strptime(row["month"], "%Y-%m")
        if start <= dt <= end:
            months.append(row["month"])
            precip.append(row["PRECTOTCORR"])
            t2m.append(row["T2M"])
            t2m_max.append(row["T2M_MAX"])

    return {
        "months": months,
        "PRECTOTCORR": precip,
        "T2M": t2m,
        "T2M_MAX": t2m_max,
    }


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
    if USE_BUNDLED_DATA:
        return pd.DataFrame()  # will trigger bundled fallback in callers

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
    Falls back to bundled data when NASA POWER API is unreachable.
    """
    daily = get_weather_daily(start_date, end_date)
    if daily.empty:
        # Fall back to bundled monthly data
        return _get_bundled_monthly(start_date, end_date)

    # Replace NASA fill values (-999) with NaN
    daily = daily.replace(-999, float("nan"))

    monthly = daily.resample("MS").agg(
        {
            "PRECTOTCORR": "sum",   # total monthly precipitation
            "T2M": "mean",          # mean temperature
            "T2M_MAX": "max",       # peak temperature (heatwave proxy)
        }
    )

    # Drop months that are entirely NaN, and fill remaining NaN with None for JSON
    monthly = monthly.dropna(how="all")

    def _safe_list(series):
        """Convert to list replacing NaN with None (JSON null)."""
        return [None if pd.isna(v) else round(v, 2) for v in series]

    return {
        "months": monthly.index.strftime("%Y-%m").tolist(),
        "PRECTOTCORR": _safe_list(monthly["PRECTOTCORR"]),
        "T2M": _safe_list(monthly["T2M"]),
        "T2M_MAX": _safe_list(monthly["T2M_MAX"]),
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
        # Fall back to bundled monthly data for feature computation
        bundled = _get_bundled_monthly(start_date, end_date)
        if not bundled["months"]:
            return {
                "rain_last_12m": None,
                "temp_mean_last_12m": None,
                "heatwave_days": None,
                "drought_proxy": None,
            }
        import numpy as _np
        rain_total = sum(bundled["PRECTOTCORR"])
        temp_mean = _np.mean(bundled["T2M"])
        # Heatwave from monthly max: count months where T2M_MAX > 35
        heatwave_days = sum(1 for t in bundled["T2M_MAX"] if t > 35) * 5  # estimate ~5 days per hot month
        n_months = len(bundled["months"])
        expected_rain = 800.0 * (n_months / 12.0)
        drought_proxy = (rain_total - expected_rain) / (expected_rain + 1e-6)
        return {
            "rain_last_12m": round(float(rain_total), 2),
            "temp_mean_last_12m": round(float(temp_mean), 2),
            "heatwave_days": heatwave_days,
            "drought_proxy": round(float(drought_proxy), 4),
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


def _bundled_open_meteo_forecast(days: int) -> dict:
    """Fallback 7-day-like forecast for frontend resilience."""
    base = date.today()
    tmax = [11.0, 13.0, 14.0, 12.0, 10.0, 9.0, 11.0, 13.0, 14.0, 12.0]
    tmin = [4.0, 5.0, 6.0, 5.0, 3.0, 2.0, 4.0, 5.0, 6.0, 5.0]
    precip = [1.2, 0.0, 3.5, 6.2, 0.8, 0.0, 2.1, 0.3, 1.8, 4.0]
    wind = [17.0, 14.0, 20.0, 23.0, 16.0, 13.0, 18.0, 15.0, 14.0, 19.0]
    weather_codes = [3, 1, 61, 63, 2, 0, 3, 1, 2, 61]

    return {
        "source": "open-meteo-bundled-fallback",
        "latitude": 46.603354,
        "longitude": 1.888334,
        "timezone": "Europe/Paris",
        "days": [
            {
                "date": (base + timedelta(days=i)).isoformat(),
                "temp_max_c": tmax[i],
                "temp_min_c": tmin[i],
                "precip_mm": precip[i],
                "wind_kmh": wind[i],
                "weather_code": weather_codes[i],
            }
            for i in range(max(1, min(days, 10)))
        ],
    }


def get_open_meteo_france_forecast(days: int = 7, lat: float = 46.603354, lon: float = 1.888334) -> dict:
    """
    Fetch France 7-day forecast from Open-Meteo.

    Returns
    -------
    dict:
      - source, latitude, longitude, timezone
      - days: [{date, temp_max_c, temp_min_c, precip_mm, wind_kmh, weather_code}, ...]
    """
    safe_days = max(1, min(days, 10))
    base_url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "forecast_days": safe_days,
        "timezone": "Europe/Paris",
        "daily": ",".join(
            [
                "weather_code",
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_sum",
                "wind_speed_10m_max",
            ]
        ),
    }

    try:
        resp = requests.get(base_url, params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        daily = payload.get("daily", {})
        dates = daily.get("time", []) or []
        tmax = daily.get("temperature_2m_max", []) or []
        tmin = daily.get("temperature_2m_min", []) or []
        precip = daily.get("precipitation_sum", []) or []
        wind = daily.get("wind_speed_10m_max", []) or []
        weather_codes = daily.get("weather_code", []) or []

        if not dates:
            return _bundled_open_meteo_forecast(safe_days)

        out_days = []
        for idx, day in enumerate(dates):
            out_days.append(
                {
                    "date": str(day),
                    "temp_max_c": round(float(tmax[idx]), 1) if idx < len(tmax) and tmax[idx] is not None else None,
                    "temp_min_c": round(float(tmin[idx]), 1) if idx < len(tmin) and tmin[idx] is not None else None,
                    "precip_mm": round(float(precip[idx]), 1) if idx < len(precip) and precip[idx] is not None else None,
                    "wind_kmh": round(float(wind[idx]), 1) if idx < len(wind) and wind[idx] is not None else None,
                    "weather_code": int(weather_codes[idx]) if idx < len(weather_codes) and weather_codes[idx] is not None else None,
                }
            )

        return {
            "source": "open-meteo",
            "latitude": payload.get("latitude", lat),
            "longitude": payload.get("longitude", lon),
            "timezone": payload.get("timezone", "Europe/Paris"),
            "days": out_days,
        }
    except requests.RequestException:
        return _bundled_open_meteo_forecast(safe_days)
