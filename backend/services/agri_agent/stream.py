from __future__ import annotations

import asyncio
import re
from typing import AsyncIterator

try:
    from langgraph.graph import END, START, StateGraph
except Exception:  # pragma: no cover - optional dependency
    END = "__end__"
    START = "__start__"
    StateGraph = None

from .stages import (
    bio_monitor_agent,
    climate_agent,
    geocoding_agent,
    market_overview_agent,
    orchestrator_agent,
    query_analysis_agent,
    yield_analysis_agent,
)
from .types import AgentState


def build_agent_graph():
    if StateGraph is None:
        return None

    g = StateGraph(AgentState)
    g.add_node("query_analysis_agent", query_analysis_agent)
    g.add_node("geocoding_agent", geocoding_agent)
    g.add_node("yield_analysis_agent", yield_analysis_agent)
    g.add_node("market_overview_agent", market_overview_agent)
    g.add_node("climate_agent", climate_agent)
    g.add_node("bio_monitor_agent", bio_monitor_agent)
    g.add_node("orchestrator_agent", orchestrator_agent)

    g.add_edge(START, "query_analysis_agent")
    g.add_edge("query_analysis_agent", "geocoding_agent")
    g.add_edge("geocoding_agent", "yield_analysis_agent")
    g.add_edge("yield_analysis_agent", "market_overview_agent")
    g.add_edge("market_overview_agent", "climate_agent")
    g.add_edge("climate_agent", "bio_monitor_agent")
    g.add_edge("bio_monitor_agent", "orchestrator_agent")
    g.add_edge("orchestrator_agent", END)

    return g.compile()


def _chunk_text(text: str, size: int = 24):
    for i in range(0, len(text), size):
        yield text[i:i + size]


def _sanitize_assistant_text(text: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"</?think>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


_STAGE_LABEL = {
    "query_analysis_agent": "Analyzing user query",
    "geocoding_agent": "Resolving location",
    "yield_analysis_agent": "Running yield analysis",
    "market_overview_agent": "Collecting market overview",
    "climate_agent": "Checking climate risks",
    "bio_monitor_agent": "Assessing biological risk",
    "orchestrator_agent": "Generating final advisory",
}

_STAGE_ORDER = [
    "query_analysis_agent",
    "geocoding_agent",
    "yield_analysis_agent",
    "market_overview_agent",
    "climate_agent",
    "bio_monitor_agent",
    "orchestrator_agent",
]


def _label_with_details(node: str, output: dict | None) -> str:
    base = _STAGE_LABEL.get(node, node)
    idx = (_STAGE_ORDER.index(node) + 1) if node in _STAGE_ORDER else 0
    total = len(_STAGE_ORDER)
    prefix = f"[{idx}/{total}] " if idx else ""

    if not isinstance(output, dict):
        return f"{prefix}{base}"

    if node == "query_analysis_agent":
        crop = output.get("crop")
        loc = output.get("location_name")
        if crop and loc:
            return f"{prefix}{base} · crop={crop}, location={loc}"
    elif node == "geocoding_agent":
        bbox = output.get("bbox")
        if isinstance(bbox, list) and len(bbox) == 4:
            return f"{prefix}{base} · bbox ready"
    elif node == "yield_analysis_agent":
        pixels = output.get("yield_data", {}).get("total_classified_pixels")
        if pixels is not None:
            return f"{prefix}{base} · pixels={pixels}"
    elif node == "market_overview_agent":
        trend = output.get("market_data", {}).get("price_trend")
        if trend:
            return f"{prefix}{base} · trend={trend}"
    elif node == "climate_agent":
        c = output.get("climate_data", {})
        if c:
            return f"{prefix}{base} · heat={c.get('heat_risk')}, dry={c.get('dry_risk')}"
    elif node == "bio_monitor_agent":
        risk = output.get("risk_score")
        if risk is not None:
            return f"{prefix}{base} · risk={risk}"
    elif node == "orchestrator_agent":
        return f"{prefix}{base} · drafting advisory"

    return f"{prefix}{base}"


async def stream_agent_events(user_query: str) -> AsyncIterator[dict]:
    state: AgentState = {"user_query": user_query}
    yield {"type": "stage", "stage": "start", "label": f"[0/{len(_STAGE_ORDER)}] Starting agent"}

    node_fns = [
        ("query_analysis_agent", query_analysis_agent),
        ("geocoding_agent", geocoding_agent),
        ("yield_analysis_agent", yield_analysis_agent),
        ("market_overview_agent", market_overview_agent),
        ("climate_agent", climate_agent),
        ("bio_monitor_agent", bio_monitor_agent),
        ("orchestrator_agent", orchestrator_agent),
    ]
    for node, fn in node_fns:
        # Emit stage before running heavy logic so frontend can always show progress immediately.
        yield {"type": "stage", "stage": node, "label": _label_with_details(node, {})}
        await asyncio.sleep(0)
        output = await asyncio.to_thread(fn, state)
        if isinstance(output, dict):
            state.update(output)
        yield {"type": "stage", "stage": node, "label": _label_with_details(node, output)}
        await asyncio.sleep(0)

    final_text = state.get("final_advisory") or "No advisory was generated."
    final_text = _sanitize_assistant_text(str(final_text))
    yield {"type": "stage", "stage": "finalize", "label": f"[{len(_STAGE_ORDER)}/{len(_STAGE_ORDER)}] Finalizing response"}
    for part in _chunk_text(final_text):
        yield {"type": "delta", "delta": part}
