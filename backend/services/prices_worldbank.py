"""
World Bank commodity prices service — historical wheat/maize price data.

Source: World Bank Pink Sheet (monthly Excel download).
For demo robustness we include a small bundled series.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import requests
from io import BytesIO

from config import CROP_CONFIG, WORLDBANK_COMMODITIES_URL


# ─── Bundled monthly wheat price (USD/mt) — sample ───────────────
_BUNDLED_PRICES: dict[str, list[dict]] = {
    "wheat": [
        {"date": "2022-01", "price": 340.0},
        {"date": "2022-02", "price": 350.0},
        {"date": "2022-03", "price": 480.0},
        {"date": "2022-04", "price": 440.0},
        {"date": "2022-05", "price": 430.0},
        {"date": "2022-06", "price": 400.0},
        {"date": "2022-07", "price": 350.0},
        {"date": "2022-08", "price": 340.0},
        {"date": "2022-09", "price": 350.0},
        {"date": "2022-10", "price": 340.0},
        {"date": "2022-11", "price": 330.0},
        {"date": "2022-12", "price": 320.0},
        {"date": "2023-01", "price": 310.0},
        {"date": "2023-02", "price": 305.0},
        {"date": "2023-03", "price": 295.0},
        {"date": "2023-04", "price": 280.0},
        {"date": "2023-05", "price": 270.0},
        {"date": "2023-06", "price": 265.0},
        {"date": "2023-07", "price": 275.0},
        {"date": "2023-08", "price": 270.0},
        {"date": "2023-09", "price": 268.0},
        {"date": "2023-10", "price": 260.0},
        {"date": "2023-11", "price": 258.0},
        {"date": "2023-12", "price": 262.0},
        {"date": "2024-01", "price": 265.0},
        {"date": "2024-02", "price": 260.0},
        {"date": "2024-03", "price": 255.0},
        {"date": "2024-04", "price": 258.0},
        {"date": "2024-05", "price": 262.0},
        {"date": "2024-06", "price": 260.0},
        {"date": "2024-07", "price": 255.0},
        {"date": "2024-08", "price": 250.0},
        {"date": "2024-09", "price": 248.0},
        {"date": "2024-10", "price": 252.0},
        {"date": "2024-11", "price": 250.0},
        {"date": "2024-12", "price": 255.0},
    ],
}


def _try_download_worldbank(crop: str) -> Optional[pd.DataFrame]:
    """
    Attempt to download the World Bank Pink Sheet Excel and parse
    the relevant commodity price column.
    """
    cfg = CROP_CONFIG.get(crop)
    if cfg is None:
        return None

    series_name = cfg["price_series_name"]

    try:
        resp = requests.get(WORLDBANK_COMMODITIES_URL, timeout=60)
        resp.raise_for_status()
        xls = pd.ExcelFile(BytesIO(resp.content), engine="openpyxl")

        # The "Monthly Prices" sheet usually has commodity columns
        sheet = None
        for name in xls.sheet_names:
            if "monthly" in name.lower() or "price" in name.lower():
                sheet = name
                break
        if sheet is None:
            sheet = xls.sheet_names[0]

        df = xls.parse(sheet)

        # Try to find the right column
        target_col = None
        for col in df.columns:
            if series_name.lower() in str(col).lower():
                target_col = col
                break

        if target_col is None:
            return None

        # First column is usually the date
        date_col = df.columns[0]
        out = df[[date_col, target_col]].dropna()
        out.columns = ["date", "price"]
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
        out = out.dropna(subset=["date"])
        out["price"] = pd.to_numeric(out["price"], errors="coerce")
        return out.sort_values("date").reset_index(drop=True)

    except Exception as exc:
        print(f"[prices_worldbank] Download failed: {exc}")
        return None


def get_price_history(crop: str = "wheat") -> pd.DataFrame:
    """
    Return a DataFrame with columns [date, price] (monthly USD/mt).
    Tries World Bank download first, falls back to bundled data.
    """
    df = _try_download_worldbank(crop)
    if df is not None and not df.empty:
        return df

    bundled = _BUNDLED_PRICES.get(crop, [])
    if not bundled:
        return pd.DataFrame(columns=["date", "price"])

    df = pd.DataFrame(bundled)
    df["date"] = pd.to_datetime(df["date"])
    return df


def compute_price_features(crop: str = "wheat") -> dict:
    """
    Derive price-based features for the prediction pipeline.

    Returns
    -------
    dict with keys: price_lag_1, price_lag_3, price_volatility
    """
    df = get_price_history(crop)
    if df.empty or len(df) < 4:
        return {
            "price_lag_1": None,
            "price_lag_3": None,
            "price_volatility": None,
        }

    prices = df["price"].values
    price_lag_1 = float(prices[-1])
    price_lag_3 = float(prices[-3])

    # Volatility: std of last 6 months (or whatever is available)
    window = prices[-min(6, len(prices)):]
    volatility = float(window.std())

    return {
        "price_lag_1": round(price_lag_1, 2),
        "price_lag_3": round(price_lag_3, 2),
        "price_volatility": round(volatility, 2),
    }
