from __future__ import annotations

import asyncio
import re
import threading
from typing import Any, AsyncIterator

from . import core
from services.agri_agent.stream import stream_agent_events as stream_fallback_events

_GRAPH = None

_STAGE_LABEL = {
    "query_analysis_agent": "Query analysis",
    "query_validation": "Validation",
    "clarification_node": "Clarification",
    "geocoding_agent": "Geocoding",
    "geocode_dispatch": "Dispatch",
    "yield_analysis_agent": "Yield analysis",
    "market_overview_agent": "Market overview",
    "climate_agent": "Climate",
    "bio_monitor": "Bio monitor",
    "climate_priority": "Climate priority",
    "emergency_dispatcher": "Emergency dispatcher",
    "orchestrator": "Orchestrator",
}


def _get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = core.build_graph()
    return _GRAPH


def _chunk_text(text: str, size: int = 24):
    for i in range(0, len(text), size):
        yield text[i:i + size]


def _sanitize_assistant_text(text: str) -> str:
    # Remove hidden reasoning tags that some models may emit.
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"</?think>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def _short_details(node: str, output: dict[str, Any] | None) -> str:
    if not isinstance(output, dict):
        return ""
    if node == "query_analysis_agent":
        crop = output.get("crop_type")
        if crop:
            return f"crop={crop}"
    if node == "geocoding_agent":
        status = output.get("geocode_status")
        if status:
            return f"status={status}"
    if node == "yield_analysis_agent":
        data = output.get("yield_analysis_data", {})
        crops = data.get("crops", {}) if isinstance(data, dict) else {}
        if crops:
            return f"groups={len(crops)}"
    if node == "market_overview_agent":
        data = output.get("market_overview_data", {})
        prices = data.get("prices", {}) if isinstance(data, dict) else {}
        if prices:
            return f"crops={len(prices)}"
    if node == "bio_monitor":
        bio = output.get("bio_monitor", {})
        if isinstance(bio, dict) and bio.get("risk_score") is not None:
            return f"risk={bio.get('risk_score')}"
    if node == "orchestrator":
        dbg = output.get("orchestrator_debug")
        if dbg:
            return dbg
    return ""


async def stream_agent_events(user_query: str) -> AsyncIterator[dict[str, Any]]:
    try:
        graph = _get_graph()
    except Exception:
        # Fallback keeps frontend usable when langgraph is missing in runtime env.
        async for evt in stream_fallback_events(user_query):
            yield evt
        return
    initial_state: core.AgriState = {
        "user_query": user_query,
        "run_mode": "interactive",
        "is_emergency": False,
    }

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    def emit(item: dict[str, Any] | None):
        loop.call_soon_threadsafe(queue.put_nowait, item)

    def worker():
        rolling_state: dict[str, Any] = dict(initial_state)
        try:
            emit({"type": "stage", "stage": "start", "label": "Starting agent graph"})
            for updates in graph.stream(initial_state, stream_mode="updates"):
                for node, output in updates.items():
                    if isinstance(output, dict):
                        rolling_state.update(output)
                    base = _STAGE_LABEL.get(node, node)
                    details = _short_details(node, output if isinstance(output, dict) else None)
                    label = f"{base} · {details}" if details else base
                    emit({"type": "stage", "stage": node, "label": label})

            final_text = str(rolling_state.get("final_advisory") or "No final advisory generated.")
            final_text = _sanitize_assistant_text(final_text)
            emit({"type": "stage", "stage": "finalize", "label": "Finalizing response"})
            for part in _chunk_text(final_text):
                emit({"type": "delta", "delta": part})
        except Exception as exc:  # pragma: no cover
            emit({"type": "error", "error": str(exc)})
        finally:
            emit(None)

    threading.Thread(target=worker, daemon=True).start()

    while True:
        item = await queue.get()
        if item is None:
            break
        yield item
