from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    user_query: str
    crop: str
    location_name: str
    bbox: list[float]
    date_range: str
    yield_data: dict[str, Any]
    market_data: dict[str, Any]
    climate_data: dict[str, Any]
    risk_score: float
    final_advisory: str
