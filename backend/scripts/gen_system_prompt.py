"""Generate agent system prompt market context file."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.market_finance import (
    build_market_signals_response,
    get_market_snapshot,
    get_latest_wasde,
    supply_demand_regime,
    ASSET_LABELS,
)

snapshot = get_market_snapshot()
assets = snapshot.get("assets", {})

lines = []
lines.append("# AgriIntel — Market Context for Agent System Prompt")
lines.append(f"# Generated: {snapshot.get('as_of', 'unknown')}")
lines.append(f"# Data through: {snapshot.get('data_through', 'unknown')}")
lines.append("")
lines.append("## Current Market Prices & Momentum")
lines.append("")
lines.append("| Asset | Close | 1w | 4w | 12w | Vol(4w) |")
lines.append("|-------|-------|-----|-----|------|---------|")

for sym, label in ASSET_LABELS.items():
    a = assets.get(sym, {})
    c = a.get("latest_close", "N/A")
    r1 = f"{a['ret_1w']:+.1%}" if a.get("ret_1w") is not None else "N/A"
    r4 = f"{a['ret_4w']:+.1%}" if a.get("ret_4w") is not None else "N/A"
    r12 = f"{a['ret_12w']:+.1%}" if a.get("ret_12w") is not None else "N/A"
    v4 = f"{a['vol_4w']:.1%}" if a.get("vol_4w") is not None else "N/A"
    lines.append(f"| {label} | {c} | {r1} | {r4} | {r12} | {v4} |")

lines.append("")
lines.append("## Global Supply/Demand (USDA WASDE)")
lines.append("")
for crop in ["wheat", "corn"]:
    w = get_latest_wasde(crop)
    if w:
        regime = supply_demand_regime(w["stock_to_use"])
        lines.append(
            f"- **{crop.capitalize()}** ({w['marketing_year']}): "
            f"ending stocks {w['ending_stocks_mmt']} MMT / use {w['total_use_mmt']} MMT, "
            f"stocks-to-use {w['stock_to_use']:.1%}, regime: **{regime}**"
        )

lines.append("")
lines.append("## Key Market Narratives")
lines.append("")
signals = build_market_signals_response(crop="wheat", lookback_weeks=12)
for n in signals.get("narrative", []):
    lines.append(f"- {n}")

lines.append("")
lines.append("## Interpretation Guidelines")
lines.append("")
lines.append("- Stocks-to-use < 25%: TIGHT supply -> elevated price/vol risk")
lines.append("- Stocks-to-use > 35%: LOOSE supply -> price upside limited")
lines.append("- EUR weakness = export tailwind for French/EU crops")
lines.append("- Oil up = cost/inflation support to food prices (fertilizer, transport)")
lines.append("- Rising rates = tighter liquidity, may dampen speculative commodity flows")
lines.append("- Wheat futures (CBOT) in USD cents/bushel; 1 bushel wheat = 27.216 kg")
lines.append("- Corn futures (CBOT) in USD cents/bushel; 1 bushel corn = 25.401 kg")

text = "\n".join(lines)
out_path = os.path.join(os.path.dirname(__file__), "..", "data", "agent_system_prompt_market.md")
with open(out_path, "w") as f:
    f.write(text)

print(text)
print()
print(f"Saved to {out_path}")
