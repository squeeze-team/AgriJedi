"""Commodity prices service — historical wheat/maize/grape price data.

Primary source: FRED (Federal Reserve Economic Data) — IMF Primary
Commodity Prices series (USD/mt, monthly).
Fallback source: World Bank Pink Sheet (monthly Excel download).
For demo robustness we include a bundled series with real FRED values.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import requests
from io import BytesIO

from config import CROP_CONFIG, WORLDBANK_COMMODITIES_URL, USE_BUNDLED_DATA

# ─── FRED (Federal Reserve Economic Data) CSV endpoint ────────────
# Series IDs from IMF via FRED:
#   PWHEAMTUSDM = Wheat, US SRW, USD/mt
#   PMAIZMTUSDM = Maize, US No.2 Yellow, USD/mt
_FRED_SERIES = {
    "wheat": "PWHEAMTUSDM",
    "maize": "PMAIZMTUSDM",
}
_FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


# ─── Bundled monthly commodity prices (USD/mt) ───────────────────
# Wheat & Maize: REAL data from FRED (IMF Primary Commodity Prices)
#   Wheat = PWHEAMTUSDM, Maize = PMAIZMTUSDM
# Grape: Proxy estimate (no FRED series available)
_BUNDLED_PRICES: dict[str, list[dict]] = {
    # ── Wheat (FRED: PWHEAMTUSDM) — IMF wheat, US SRW, USD/mt ──
    "wheat": [
        {"date": "2022-01", "price": 326.08},
        {"date": "2022-02", "price": 347.50},
        {"date": "2022-03", "price": 387.67},
        {"date": "2022-04", "price": 406.03},
        {"date": "2022-05", "price": 444.16},  # Ukraine-war peak
        {"date": "2022-06", "price": 397.65},
        {"date": "2022-07", "price": 321.98},
        {"date": "2022-08", "price": 323.02},
        {"date": "2022-09", "price": 346.32},
        {"date": "2022-10", "price": 353.71},
        {"date": "2022-11", "price": 344.33},
        {"date": "2022-12", "price": 323.65},
        {"date": "2023-01", "price": 320.10},
        {"date": "2023-02", "price": 332.41},
        {"date": "2023-03", "price": 309.43},
        {"date": "2023-04", "price": 312.81},
        {"date": "2023-05", "price": 299.44},
        {"date": "2023-06", "price": 282.28},
        {"date": "2023-07", "price": 278.62},
        {"date": "2023-08", "price": 241.41},
        {"date": "2023-09", "price": 229.39},
        {"date": "2023-10", "price": 216.46},
        {"date": "2023-11", "price": 216.00},
        {"date": "2023-12", "price": 229.63},
        {"date": "2024-01", "price": 226.08},
        {"date": "2024-02", "price": 219.24},
        {"date": "2024-03", "price": 211.84},
        {"date": "2024-04", "price": 208.38},
        {"date": "2024-05", "price": 227.43},
        {"date": "2024-06", "price": 205.23},
        {"date": "2024-07", "price": 183.23},
        {"date": "2024-08", "price": 175.51},
        {"date": "2024-09", "price": 188.51},
        {"date": "2024-10", "price": 197.37},
        {"date": "2024-11", "price": 185.73},
        {"date": "2024-12", "price": 185.79},
        {"date": "2025-01", "price": 190.63},
        {"date": "2025-02", "price": 190.10},
        {"date": "2025-03", "price": 179.61},
        {"date": "2025-04", "price": 174.82},
        {"date": "2025-05", "price": 196.84},
        {"date": "2025-06", "price": 173.19},
        {"date": "2025-07", "price": 165.27},
        {"date": "2025-08", "price": 159.31},
        {"date": "2025-09", "price": 155.12},
        {"date": "2025-10", "price": 157.39},
        {"date": "2025-11", "price": 169.20},
        {"date": "2025-12", "price": 165.63},
        {"date": "2026-01", "price": 169.25},
    ],
    # ── Maize (FRED: PMAIZMTUSDM) — IMF maize, US No.2 Yellow, USD/mt ──
    "maize": [
        {"date": "2022-01", "price": 276.72},
        {"date": "2022-02", "price": 292.67},
        {"date": "2022-03", "price": 335.93},
        {"date": "2022-04", "price": 348.51},  # Ukraine-war peak
        {"date": "2022-05", "price": 344.91},
        {"date": "2022-06", "price": 335.72},
        {"date": "2022-07", "price": 312.68},
        {"date": "2022-08", "price": 293.93},
        {"date": "2022-09", "price": 312.55},
        {"date": "2022-10", "price": 343.55},  # Oct rebound
        {"date": "2022-11", "price": 320.93},
        {"date": "2022-12", "price": 302.24},
        {"date": "2023-01", "price": 302.84},
        {"date": "2023-02", "price": 298.25},
        {"date": "2023-03", "price": 284.96},
        {"date": "2023-04", "price": 291.18},
        {"date": "2023-05", "price": 268.17},
        {"date": "2023-06", "price": 266.94},
        {"date": "2023-07", "price": 235.27},
        {"date": "2023-08", "price": 207.68},
        {"date": "2023-09", "price": 223.85},
        {"date": "2023-10", "price": 221.90},
        {"date": "2023-11", "price": 209.04},
        {"date": "2023-12", "price": 207.40},
        {"date": "2024-01", "price": 198.76},
        {"date": "2024-02", "price": 188.95},
        {"date": "2024-03", "price": 190.23},
        {"date": "2024-04", "price": 190.90},
        {"date": "2024-05", "price": 201.02},
        {"date": "2024-06", "price": 191.24},
        {"date": "2024-07", "price": 177.77},
        {"date": "2024-08", "price": 169.30},
        {"date": "2024-09", "price": 183.66},
        {"date": "2024-10", "price": 189.59},
        {"date": "2024-11", "price": 201.31},
        {"date": "2024-12", "price": 202.83},
        {"date": "2025-01", "price": 214.36},
        {"date": "2025-02", "price": 221.25},
        {"date": "2025-03", "price": 207.75},
        {"date": "2025-04", "price": 215.57},
        {"date": "2025-05", "price": 204.81},
        {"date": "2025-06", "price": 195.72},
        {"date": "2025-07", "price": 192.45},
        {"date": "2025-08", "price": 183.02},
        {"date": "2025-09", "price": 196.15},
        {"date": "2025-10", "price": 198.02},
        {"date": "2025-11", "price": 201.66},
        {"date": "2025-12", "price": 205.32},
        {"date": "2026-01", "price": 203.90},
    ],
    # ── Grape (proxy) — No FRED series; OIV / France contract estimates ──
    # Grape prices follow wine-market cycles, NOT grain markets.
    # Pattern: post-Covid recovery → 2022 frost damage spike → 2023
    # oversupply correction → 2024-25 stabilization.
    "grape": [
        {"date": "2022-01", "price": 780.0},
        {"date": "2022-02", "price": 790.0},
        {"date": "2022-03", "price": 805.0},
        {"date": "2022-04", "price": 830.0},  # spring frost concerns
        {"date": "2022-05", "price": 855.0},
        {"date": "2022-06", "price": 870.0},  # peak — low 2021 harvest
        {"date": "2022-07", "price": 865.0},
        {"date": "2022-08", "price": 850.0},
        {"date": "2022-09", "price": 840.0},  # good 2022 vintage eases supply
        {"date": "2022-10", "price": 825.0},
        {"date": "2022-11", "price": 815.0},
        {"date": "2022-12", "price": 810.0},
        {"date": "2023-01", "price": 800.0},
        {"date": "2023-02", "price": 795.0},
        {"date": "2023-03", "price": 785.0},
        {"date": "2023-04", "price": 770.0},
        {"date": "2023-05", "price": 755.0},
        {"date": "2023-06", "price": 740.0},
        {"date": "2023-07", "price": 730.0},
        {"date": "2023-08", "price": 710.0},  # mildew pressure depresses
        {"date": "2023-09", "price": 695.0},
        {"date": "2023-10", "price": 680.0},  # oversupply; EU vine-pull scheme
        {"date": "2023-11", "price": 670.0},
        {"date": "2023-12", "price": 665.0},
        {"date": "2024-01", "price": 660.0},
        {"date": "2024-02", "price": 655.0},
        {"date": "2024-03", "price": 650.0},
        {"date": "2024-04", "price": 645.0},
        {"date": "2024-05", "price": 648.0},
        {"date": "2024-06", "price": 655.0},
        {"date": "2024-07", "price": 660.0},  # small 2024 harvest expected
        {"date": "2024-08", "price": 670.0},
        {"date": "2024-09", "price": 685.0},
        {"date": "2024-10", "price": 690.0},
        {"date": "2024-11", "price": 695.0},
        {"date": "2024-12", "price": 700.0},
        {"date": "2025-01", "price": 705.0},
        {"date": "2025-02", "price": 710.0},
        {"date": "2025-03", "price": 715.0},
        {"date": "2025-04", "price": 718.0},
        {"date": "2025-05", "price": 720.0},
        {"date": "2025-06", "price": 725.0},
        {"date": "2025-07", "price": 722.0},
        {"date": "2025-08", "price": 718.0},
        {"date": "2025-09", "price": 712.0},
        {"date": "2025-10", "price": 708.0},
        {"date": "2025-11", "price": 705.0},
        {"date": "2025-12", "price": 710.0},
        {"date": "2026-01", "price": 715.0},
    ],
}


def _try_download_fred(crop: str) -> Optional[pd.DataFrame]:
    """
    Download monthly commodity prices from FRED (IMF series).
    Works for wheat and maize. Returns None for unsupported crops.
    """
    series_id = _FRED_SERIES.get(crop)
    if series_id is None:
        return None

    try:
        params = {
            "id": series_id,
            "cosd": "2022-01-01",
            "coed": "2026-12-01",
        }
        resp = requests.get(_FRED_CSV_URL, params=params, timeout=30)
        resp.raise_for_status()

        from io import StringIO
        df = pd.read_csv(StringIO(resp.text))
        # Columns: observation_date, <SERIES_ID>
        col = [c for c in df.columns if c != "observation_date"][0]
        df = df.rename(columns={"observation_date": "date", col: "price"})
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["price"] = pd.to_numeric(df["price"], errors="coerce")
        df = df.dropna(subset=["date", "price"])
        print(f"[prices] FRED {series_id}: loaded {len(df)} rows")
        return df.sort_values("date").reset_index(drop=True)

    except Exception as exc:
        print(f"[prices] FRED download failed: {exc}")
        return None


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
    if not USE_BUNDLED_DATA:
        # Try FRED first (faster, more reliable), then World Bank
        df = _try_download_fred(crop)
        if df is not None and not df.empty:
            return df
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
