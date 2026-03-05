"""
Market finance service — cached financial & commodity market signals.

Reads pre-downloaded data from data/ directory (produced by
scripts/download_market_data.py).  No live API calls at import time.

Provides:
  - Daily OHLCV for wheat/corn futures, EUR/USD, WTI oil, US 10Y yield
  - Weekly close + returns + volatility (long & wide format)
  - WASDE global stocks-to-use (wheat, corn)
  - Latest market snapshot (for agent system prompts)
  - Narrative generation (risk regime, pricing flags, macro summary)
"""

from __future__ import annotations

import json
import math
import os
from typing import Any, Optional

import numpy as np
import pandas as pd

from config import USE_BUNDLED_DATA

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

# ─── Lazy-loaded caches ──────────────────────────────────────────

_daily_cache: Optional[pd.DataFrame] = None
_weekly_long_cache: Optional[pd.DataFrame] = None
_weekly_wide_cache: Optional[pd.DataFrame] = None
_snapshot_cache: Optional[dict] = None
_wasde_cache: Optional[pd.DataFrame] = None


# ─── Asset metadata ──────────────────────────────────────────────

ASSET_LABELS = {
    "wheat_fut":    "Wheat Futures (CBOT ZW=F)",
    "corn_fut":     "Corn Futures (CBOT ZC=F)",
    "eurusd":       "EUR/USD",
    "oil_wti":      "WTI Crude Oil (CL=F)",
    "us10y_yield":  "US 10-Year Treasury Yield (^TNX)",
}

ASSET_UNITS = {
    "wheat_fut":    "USD cents/bushel",
    "corn_fut":     "USD cents/bushel",
    "eurusd":       "USD per EUR",
    "oil_wti":      "USD/barrel",
    "us10y_yield":  "% yield",
}


# ─── Loaders ──────────────────────────────────────────────────────

def _load_daily() -> pd.DataFrame:
    global _daily_cache
    if _daily_cache is not None:
        return _daily_cache
    path = os.path.join(_DATA_DIR, "market_daily.csv")
    if not os.path.exists(path):
        _daily_cache = pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close", "volume"])
        return _daily_cache
    df = pd.read_csv(path, parse_dates=["date"])
    _daily_cache = df
    return df


def _load_weekly_wide() -> pd.DataFrame:
    global _weekly_wide_cache
    if _weekly_wide_cache is not None:
        return _weekly_wide_cache
    path = os.path.join(_DATA_DIR, "market_weekly.csv")
    if not os.path.exists(path):
        _weekly_wide_cache = pd.DataFrame()
        return _weekly_wide_cache
    df = pd.read_csv(path, parse_dates=["week_start"])
    _weekly_wide_cache = df
    return df


def _load_snapshot() -> dict:
    global _snapshot_cache
    if _snapshot_cache is not None:
        return _snapshot_cache
    path = os.path.join(_DATA_DIR, "market_snapshot.json")
    if not os.path.exists(path):
        _snapshot_cache = {}
        return _snapshot_cache
    with open(path) as f:
        _snapshot_cache = json.load(f)
    return _snapshot_cache


def _load_wasde() -> pd.DataFrame:
    global _wasde_cache
    if _wasde_cache is not None:
        return _wasde_cache
    path = os.path.join(_DATA_DIR, "wasde_stu.csv")
    if not os.path.exists(path):
        _wasde_cache = pd.DataFrame()
        return _wasde_cache
    _wasde_cache = pd.read_csv(path)
    return _wasde_cache


# ─── Public API ───────────────────────────────────────────────────

def get_market_snapshot() -> dict:
    """Return the pre-computed latest market snapshot (for agent prompts)."""
    return _load_snapshot()


def get_market_daily(symbol: Optional[str] = None,
                     start: Optional[str] = None,
                     end: Optional[str] = None) -> list[dict]:
    """Return daily OHLCV data, optionally filtered."""
    df = _load_daily()
    if df.empty:
        return []
    if symbol:
        df = df[df["symbol"] == symbol]
    if start:
        df = df[df["date"] >= pd.to_datetime(start)]
    if end:
        df = df[df["date"] <= pd.to_datetime(end)]
    return df.to_dict(orient="records")


def get_market_weekly_wide() -> pd.DataFrame:
    """Return wide-format weekly market features."""
    return _load_weekly_wide()


def get_wasde_data() -> list[dict]:
    """Return WASDE stocks-to-use data."""
    df = _load_wasde()
    if df.empty:
        return []
    return df.to_dict(orient="records")


def get_latest_wasde(crop: str = "wheat") -> Optional[dict]:
    """Return the latest WASDE row for a crop."""
    df = _load_wasde()
    if df.empty:
        return None
    sub = df[df["crop"] == crop]
    if sub.empty:
        return None
    return sub.iloc[-1].to_dict()


# ─── Analysis / Narrative helpers ─────────────────────────────────

def _safe(v, n=4):
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, n)
    except Exception:
        return None


def supply_demand_regime(stu: Optional[float],
                         tight_thr: float = 0.25,
                         loose_thr: float = 0.35) -> str:
    """Classify global stocks-to-use into regime."""
    if stu is None:
        return "unknown"
    if stu < tight_thr:
        return "tight"
    if stu > loose_thr:
        return "loose"
    return "normal"


def market_pricing_narrative(
    yield_risk_high: bool,
    fut_ret_4w: Optional[float],
    fut_vol_4w: Optional[float],
) -> dict:
    """
    Produce a narrative flag comparing yield risk vs market reaction.
    """
    if fut_ret_4w is None:
        return {"flag": "insufficient_data", "note": "No futures return data available."}

    flat_thr = 0.015  # 1.5% threshold for "flat"

    if yield_risk_high and abs(fut_ret_4w) < flat_thr:
        return {
            "flag": "underpriced_risk",
            "note": "Yield risk is elevated but futures are flat — market may be underpricing the shock.",
        }
    if yield_risk_high and fut_ret_4w >= flat_thr:
        return {
            "flag": "repricing",
            "note": "Futures are rallying in line with elevated yield risk — market is repricing.",
        }
    if not yield_risk_high and fut_ret_4w >= flat_thr:
        return {
            "flag": "macro_driven",
            "note": "Futures rally despite muted local yield risk — likely macro/global drivers.",
        }
    if not yield_risk_high and fut_ret_4w <= -flat_thr:
        return {
            "flag": "bearish",
            "note": "Futures declining with no yield stress — possible demand weakness or supply comfort.",
        }
    return {"flag": "mixed", "note": "Mixed signals — no dominant narrative."}


def build_market_signals_response(crop: str = "wheat",
                                   lookback_weeks: int = 52) -> dict:
    """
    Build a comprehensive market signals response for the agent endpoint.
    Combines: snapshot + weekly series + WASDE + narrative.
    """
    snapshot = _load_snapshot()
    assets = snapshot.get("assets", {})

    # --- Per-asset latest stats ---
    asset_summaries = {}
    for sym, label in ASSET_LABELS.items():
        a = assets.get(sym, {})
        asset_summaries[sym] = {
            "label": label,
            "unit": ASSET_UNITS.get(sym, ""),
            "latest_close": _safe(a.get("latest_close")),
            "ret_1w": _safe(a.get("ret_1w")),
            "ret_4w": _safe(a.get("ret_4w")),
            "ret_12w": _safe(a.get("ret_12w")),
            "vol_4w": _safe(a.get("vol_4w")),
            "vol_8w": _safe(a.get("vol_8w")),
        }

    # --- Weekly price series (last N weeks) for charting ---
    wide = _load_weekly_wide()
    series = {}
    if not wide.empty:
        recent = wide.tail(lookback_weeks)
        weeks = recent["week_start"].dt.strftime("%Y-%m-%d").tolist()
        series["weeks"] = weeks
        for sym in ASSET_LABELS.keys():
            col = f"{sym}_close"
            if col in recent.columns:
                series[sym] = [_safe(v, 2) for v in recent[col].tolist()]

    # --- WASDE supply/demand ---
    wasde_wheat = get_latest_wasde("wheat")
    wasde_corn = get_latest_wasde("corn")

    wheat_stu = wasde_wheat["stock_to_use"] if wasde_wheat else None
    corn_stu = wasde_corn["stock_to_use"] if wasde_corn else None

    supply_demand = {
        "wheat": {
            "marketing_year": wasde_wheat["marketing_year"] if wasde_wheat else None,
            "ending_stocks_mmt": wasde_wheat["ending_stocks_mmt"] if wasde_wheat else None,
            "total_use_mmt": wasde_wheat["total_use_mmt"] if wasde_wheat else None,
            "stock_to_use": wheat_stu,
            "regime": supply_demand_regime(wheat_stu),
        },
        "corn": {
            "marketing_year": wasde_corn["marketing_year"] if wasde_corn else None,
            "ending_stocks_mmt": wasde_corn["ending_stocks_mmt"] if wasde_corn else None,
            "total_use_mmt": wasde_corn["total_use_mmt"] if wasde_corn else None,
            "stock_to_use": corn_stu,
            "regime": supply_demand_regime(corn_stu),
        },
    }

    # --- Build narrative bullets ---
    narrative = []

    # Futures
    crop_sym = "wheat_fut" if crop == "wheat" else "corn_fut"
    crop_a = assets.get(crop_sym, {})
    r4 = _safe(crop_a.get("ret_4w"))
    v4 = _safe(crop_a.get("vol_4w"))
    if r4 is not None:
        direction = "up" if r4 > 0.01 else ("down" if r4 < -0.01 else "flat")
        narrative.append(
            f"{ASSET_LABELS[crop_sym]} {direction} {abs(r4):.1%} over 4 weeks "
            f"(vol {v4:.1%})." if v4 else f"{ASSET_LABELS[crop_sym]} {direction} {abs(r4):.1%} over 4 weeks."
        )

    # FX
    eurusd_a = assets.get("eurusd", {})
    fx_r4 = _safe(eurusd_a.get("ret_4w"))
    if fx_r4 is not None:
        if fx_r4 < -0.01:
            narrative.append(f"EUR weakened {abs(fx_r4):.1%} over 4 weeks — export tailwind for EU crops.")
        elif fx_r4 > 0.01:
            narrative.append(f"EUR strengthened {abs(fx_r4):.1%} over 4 weeks — export headwind for EU crops.")
        else:
            narrative.append("EUR/USD roughly stable over 4 weeks.")

    # Oil
    oil_a = assets.get("oil_wti", {})
    oil_r4 = _safe(oil_a.get("ret_4w"))
    if oil_r4 is not None:
        if oil_r4 > 0.03:
            narrative.append(f"Oil up {oil_r4:.1%} over 4 weeks — cost & inflation support to food prices.")
        elif oil_r4 < -0.03:
            narrative.append(f"Oil down {abs(oil_r4):.1%} over 4 weeks — easing cost pressure.")
        else:
            narrative.append("Oil roughly stable over 4 weeks.")

    # Rates
    rates_a = assets.get("us10y_yield", {})
    rates_r4 = _safe(rates_a.get("ret_4w"))
    if rates_r4 is not None:
        if rates_r4 > 0.01:
            narrative.append("US 10Y yield rising — tighter liquidity environment, may dampen speculative commodity flows.")
        elif rates_r4 < -0.01:
            narrative.append("US 10Y yield falling — easing liquidity, supportive for commodity allocation.")
        else:
            narrative.append("Rates largely unchanged over 4 weeks.")

    # Supply/demand
    target_stu = wheat_stu if crop == "wheat" else corn_stu
    target_regime = supply_demand[crop if crop in ("wheat", "corn") else "wheat"]["regime"]
    if target_stu is not None:
        narrative.append(
            f"Global {crop} stocks-to-use: {target_stu:.1%} ({target_regime} regime). "
            + ("Price/volatility risk elevated under tight supply."
               if target_regime == "tight"
               else "Supply cushion limits upside price risk."
               if target_regime == "loose"
               else "Supply balanced.")
        )

    # --- Summary text for prompt ---
    summary = snapshot.get("summary_for_prompt", "")

    return {
        "endpoint": "/agent/market-signals",
        "as_of": snapshot.get("as_of"),
        "data_through": snapshot.get("data_through"),
        "crop_focus": crop,
        "assets": asset_summaries,
        "weekly_series": series,
        "supply_demand": supply_demand,
        "narrative": narrative,
        "summary_for_prompt": summary,
    }
