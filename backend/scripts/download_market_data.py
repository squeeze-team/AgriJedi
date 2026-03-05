"""
Download and cache market data for demo (offline use).

Symbols:
  - ZW=F   → CBOT wheat futures
  - ZC=F   → CBOT corn futures
  - EURUSD=X → EUR/USD exchange rate
  - CL=F   → WTI crude oil
  - ^TNX   → US 10-Year Treasury yield

Output:
  data/market_daily.csv   — long-format daily OHLCV
  data/market_weekly.csv  — weekly close + returns + volatility (pivoted)
  data/market_meta.json   — download metadata
  data/market_snapshot.json — latest values for agent system prompt
  data/wasde_stu.csv      — USDA wheat/corn stocks-to-use (manual)
"""

import os, sys, json, math
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(OUT_DIR, exist_ok=True)


# ── 1) Download daily data from Yahoo Finance ─────────────────────

SYMBOLS = {
    "ZW=F":     "wheat_fut",
    "ZC=F":     "corn_fut",
    "EURUSD=X": "eurusd",
    "CL=F":     "oil_wti",
    "^TNX":     "us10y_yield",
}

START = "2023-01-01"
END   = "2026-03-06"

all_rows = []
meta = {}

for sym, label in SYMBOLS.items():
    print(f"Downloading {sym} ({label}) ...")
    try:
        df = yf.download(sym, start=START, end=END, auto_adjust=False, progress=False)
        if df is None or df.empty:
            print(f"  WARNING: no data for {sym}")
            continue
        df = df.reset_index()
        # yfinance may return MultiIndex columns
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]

        n = len(df)
        d0 = df["Date"].min().strftime("%Y-%m-%d")
        d1 = df["Date"].max().strftime("%Y-%m-%d")
        latest = float(df["Close"].iloc[-1])
        print(f"  OK  {n} rows  {d0} → {d1}  latest={latest:.2f}")

        for _, row in df.iterrows():
            all_rows.append({
                "date":   row["Date"].strftime("%Y-%m-%d"),
                "symbol": label,
                "open":   round(float(row["Open"]), 4) if pd.notna(row["Open"]) else None,
                "high":   round(float(row["High"]), 4) if pd.notna(row["High"]) else None,
                "low":    round(float(row["Low"]), 4)  if pd.notna(row["Low"])  else None,
                "close":  round(float(row["Close"]), 4) if pd.notna(row["Close"]) else None,
                "volume": int(row["Volume"]) if "Volume" in row and pd.notna(row["Volume"]) else None,
            })
        meta[label] = {
            "yahoo_symbol": sym,
            "rows": n,
            "start": d0,
            "end": d1,
            "latest_close": round(latest, 4),
        }
    except Exception as e:
        print(f"  ERROR {sym}: {e}")

df_daily = pd.DataFrame(all_rows)
daily_path = os.path.join(OUT_DIR, "market_daily.csv")
df_daily.to_csv(daily_path, index=False)
print(f"\nSaved {len(df_daily)} rows → {daily_path}")


# ── 2) Build weekly close + returns + volatility ──────────────────

def build_weekly(df_daily):
    d = df_daily.copy()
    d["date"] = pd.to_datetime(d["date"])
    d["week_start"] = d["date"].dt.to_period("W-MON").dt.start_time
    # weekly last close
    w = d.groupby(["symbol", "week_start"], as_index=False)["close"].last()
    w = w.sort_values(["symbol", "week_start"])
    # log return
    w["ret_1w"] = w.groupby("symbol")["close"].transform(
        lambda s: np.log(s / s.shift(1))
    )
    # 4-week rolling volatility
    w["vol_4w"] = w.groupby("symbol")["ret_1w"].transform(
        lambda s: s.rolling(4).std()
    )
    # 8-week rolling volatility (for FX/macro)
    w["vol_8w"] = w.groupby("symbol")["ret_1w"].transform(
        lambda s: s.rolling(8).std()
    )
    # 4-week cumulative return
    w["ret_4w"] = w.groupby("symbol")["close"].transform(
        lambda s: np.log(s / s.shift(4))
    )
    # 12-week cumulative return
    w["ret_12w"] = w.groupby("symbol")["close"].transform(
        lambda s: np.log(s / s.shift(12))
    )
    return w

df_weekly_long = build_weekly(df_daily)

# Pivot into wide format: one row per week, columns prefixed by symbol
def pivot_wide(df_long):
    dfs = []
    for field in ["close", "ret_1w", "ret_4w", "ret_12w", "vol_4w", "vol_8w"]:
        p = df_long.pivot_table(index="week_start", columns="symbol", values=field, aggfunc="last")
        p.columns = [f"{c}_{field}" for c in p.columns]
        dfs.append(p)
    wide = pd.concat(dfs, axis=1).reset_index()
    wide = wide.sort_values("week_start")
    return wide

df_weekly_wide = pivot_wide(df_weekly_long)
weekly_path = os.path.join(OUT_DIR, "market_weekly.csv")
df_weekly_wide.to_csv(weekly_path, index=False)
print(f"Saved {len(df_weekly_wide)} weeks → {weekly_path}")


# ── 3) Save metadata ─────────────────────────────────────────────

meta_path = os.path.join(OUT_DIR, "market_meta.json")
with open(meta_path, "w") as f:
    json.dump({
        "downloaded_at": datetime.now().isoformat(),
        "source": "Yahoo Finance (yfinance)",
        "period": {"start": START, "end": END},
        "symbols": meta,
    }, f, indent=2, ensure_ascii=False)
print(f"Saved metadata → {meta_path}")


# ── 4) Build latest snapshot for agent system prompt ──────────────

def safe_round(v, n=4):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return round(float(v), n)

latest_week = df_weekly_long.groupby("symbol").last().reset_index()
prev_week = df_weekly_long.groupby("symbol").nth(-2).reset_index()

snapshot = {
    "as_of": datetime.now().strftime("%Y-%m-%d"),
    "data_through": df_daily["date"].max() if len(df_daily) else "unknown",
    "assets": {},
}

for _, row in latest_week.iterrows():
    sym = row["symbol"]
    snapshot["assets"][sym] = {
        "latest_close": safe_round(row["close"]),
        "ret_1w": safe_round(row.get("ret_1w"), 4),
        "ret_4w": safe_round(row.get("ret_4w"), 4),
        "ret_12w": safe_round(row.get("ret_12w"), 4),
        "vol_4w": safe_round(row.get("vol_4w"), 4),
        "vol_8w": safe_round(row.get("vol_8w"), 4),
    }

# Add human-readable summary lines
summary_lines = []
LABELS = {
    "wheat_fut": "Wheat futures (CBOT)",
    "corn_fut": "Corn futures (CBOT)",
    "eurusd": "EUR/USD",
    "oil_wti": "WTI Crude Oil",
    "us10y_yield": "US 10Y Treasury Yield",
}
for sym, info in snapshot["assets"].items():
    label = LABELS.get(sym, sym)
    c = info["latest_close"]
    r4 = info["ret_4w"]
    v4 = info["vol_4w"]
    r4_str = f"{r4:+.1%}" if r4 is not None else "N/A"
    v4_str = f"{v4:.1%}" if v4 is not None else "N/A"
    summary_lines.append(f"- {label}: {c}  (4w return {r4_str}, 4w vol {v4_str})")

snapshot["summary_for_prompt"] = "\n".join(summary_lines)

snap_path = os.path.join(OUT_DIR, "market_snapshot.json")
with open(snap_path, "w") as f:
    json.dump(snapshot, f, indent=2, ensure_ascii=False)
print(f"Saved snapshot → {snap_path}")
print("\n=== Agent Prompt Summary ===")
print(snapshot["summary_for_prompt"])


# ── 5) Create WASDE stocks-to-use (manual reference data) ────────
#
# Source: USDA WASDE reports (2020/21 – 2025/26 est.)
# Global ending stocks / total use

wasde_rows = [
    # marketing_year, crop, ending_stocks_mmt, total_use_mmt, stock_to_use
    ("2020/21", "wheat", 295.5, 776.0, 0.381),
    ("2020/21", "corn",  291.4, 1140.0, 0.256),
    ("2021/22", "wheat", 278.2, 787.0, 0.353),
    ("2021/22", "corn",  305.5, 1196.0, 0.255),
    ("2022/23", "wheat", 267.0, 790.2, 0.338),
    ("2022/23", "corn",  297.4, 1168.0, 0.255),
    ("2023/24", "wheat", 264.3, 797.5, 0.331),
    ("2023/24", "corn",  314.2, 1216.0, 0.258),
    ("2024/25", "wheat", 260.7, 802.0, 0.325),
    ("2024/25", "corn",  293.3, 1230.0, 0.238),
    ("2025/26", "wheat", 257.8, 808.0, 0.319),  # USDA Feb 2026 est.
    ("2025/26", "corn",  288.9, 1240.0, 0.233),  # USDA Feb 2026 est.
]
wasde_df = pd.DataFrame(wasde_rows, columns=["marketing_year", "crop", "ending_stocks_mmt", "total_use_mmt", "stock_to_use"])
wasde_path = os.path.join(OUT_DIR, "wasde_stu.csv")
wasde_df.to_csv(wasde_path, index=False)
print(f"\nSaved WASDE → {wasde_path}")
print(wasde_df.to_string(index=False))


print("\n✅ All market data downloaded and cached for demo!")
