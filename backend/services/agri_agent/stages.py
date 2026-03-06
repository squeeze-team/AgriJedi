from __future__ import annotations

import os
from typing import Any

try:
    from langchain_openai import ChatOpenAI
except Exception:  # pragma: no cover - optional dependency
    ChatOpenAI = None

from .types import AgentState


LOCATION_BBOX = {
    "rhone valley": [4.67, 44.71, 4.97, 45.01],
    "beauce": [1.2, 47.8, 1.8, 48.3],
    "champagne": [3.0, 49.0, 3.8, 49.4],
    "bordeaux": [-0.8, 44.6, 0.0, 45.1],
    "france": [-5.14, 41.33, 9.56, 51.09],
}


def _default_crop() -> str:
    try:
        from config import DEFAULT_CROP as cfg_crop  # type: ignore
        return cfg_crop
    except Exception:
        return "wheat"


def _infer_crop(user_query: str) -> str:
    q = user_query.lower()
    if "maize" in q or "corn" in q:
        return "maize"
    if "grape" in q or "wine" in q:
        return "grape"
    if "wheat" in q:
        return "wheat"
    return _default_crop()


def _infer_location(user_query: str) -> tuple[str, list[float]]:
    q = user_query.lower()
    for name, bbox in LOCATION_BBOX.items():
        if name in q:
            return name.title(), bbox
    return "France", LOCATION_BBOX["france"]


def _safe_analyze_crop_ndvi(bbox: list[float], date_range: str) -> dict[str, Any]:
    try:
        from services.crop_ndvi_analysis import analyze_crop_ndvi  # type: ignore

        return analyze_crop_ndvi(bbox=bbox, date_range=date_range, resolution=350)
    except Exception:
        # Minimal fallback to keep agent streaming usable even when heavy deps are missing.
        return {
            "total_classified_pixels": 0,
            "item_id": "fallback",
            "crops": {
                "wheat": {"yield_index": 0.98, "yield_index_label": "Near baseline"},
                "maize": {"yield_index": 1.01, "yield_index_label": "Near baseline"},
                "grape": {"yield_index": 1.00, "yield_index_label": "Near baseline"},
            },
        }


def _safe_price_history(crop: str):
    try:
        from services.prices_worldbank import get_price_history  # type: ignore

        return get_price_history(crop)
    except Exception:
        return None


def _safe_weather(start_date: str, end_date: str) -> dict[str, Any]:
    try:
        from services.weather_power import get_weather_monthly  # type: ignore

        return get_weather_monthly(start_date=start_date, end_date=end_date)
    except Exception:
        return {"T2M": [], "PRECTOTCORR": [], "T2M_MAX": []}


def query_analysis_agent(state: AgentState) -> AgentState:
    crop = _infer_crop(state["user_query"])
    location_name, bbox = _infer_location(state["user_query"])
    return {
        "crop": crop,
        "location_name": location_name,
        "bbox": bbox,
        "date_range": "2025-06-01/2025-09-01",
    }


def geocoding_agent(state: AgentState) -> AgentState:
    return {
        "location_name": state.get("location_name", "France"),
        "bbox": state.get("bbox", LOCATION_BBOX["france"]),
    }


def yield_analysis_agent(state: AgentState) -> AgentState:
    bbox = state["bbox"]
    date_range = state.get("date_range", "2025-06-01/2025-09-01")
    payload = _safe_analyze_crop_ndvi(bbox=bbox, date_range=date_range)

    crop = state.get("crop", _default_crop())
    crops = payload.get("crops", {})
    selected = crops.get(crop) or next(iter(crops.values()), {})

    return {
        "yield_data": {
            "crop": crop,
            "selected": selected,
            "total_classified_pixels": payload.get("total_classified_pixels", 0),
            "source": payload.get("item_id", "bundled"),
        }
    }


def market_overview_agent(state: AgentState) -> AgentState:
    crop = state.get("crop", _default_crop())
    df = _safe_price_history(crop)
    latest_price = None
    trend = "insufficient data"

    if df is not None and hasattr(df, "empty") and not df.empty:
        prices = df["price"].tolist()
        latest_price = round(float(prices[-1]), 2)
        if len(prices) >= 6:
            recent = sum(prices[-3:]) / 3
            older = sum(prices[-6:-3]) / 3
            if recent > older * 1.02:
                trend = "rising"
            elif recent < older * 0.98:
                trend = "falling"
            else:
                trend = "stable"

    weather = _safe_weather(start_date="20250101", end_date="20251231")
    t2m = weather.get("T2M", [])
    precip = weather.get("PRECTOTCORR", [])

    market_data = {
        "crop": crop,
        "latest_price_usd_mt": latest_price,
        "price_trend": trend,
        "avg_temp_c": round(sum(t2m) / len(t2m), 1) if t2m else None,
        "total_precip_mm": round(sum(precip), 1) if precip else None,
    }
    return {"market_data": market_data}


def climate_agent(state: AgentState) -> AgentState:
    weather = _safe_weather(start_date="20250701", end_date="20250930")
    max_t = weather.get("T2M_MAX", [])
    precip = weather.get("PRECTOTCORR", [])

    heat_risk = min(1.0, (max(max_t) - 30) / 10) if max_t else 0.4
    dry_risk = min(1.0, 1 - (sum(precip) / (len(precip) * 60))) if precip else 0.5

    return {
        "climate_data": {
            "heat_risk": round(max(0.0, heat_risk), 2),
            "dry_risk": round(max(0.0, dry_risk), 2),
        }
    }


def bio_monitor_agent(state: AgentState) -> AgentState:
    selected = state.get("yield_data", {}).get("selected", {})
    yi = selected.get("yield_index")
    climate = state.get("climate_data", {})

    ndvi_risk = 0.5 if yi is None else min(1.0, max(0.0, 1.15 - float(yi)))

    heat = float(climate.get("heat_risk", 0.5))
    dry = float(climate.get("dry_risk", 0.5))
    risk_score = round(min(1.0, 0.5 * ndvi_risk + 0.3 * heat + 0.2 * dry), 2)
    return {"risk_score": risk_score}


def orchestrator_agent(state: AgentState) -> AgentState:
    crop = state.get("crop", _default_crop())
    location = state.get("location_name", "France")
    risk = state.get("risk_score", 0.5)
    market = state.get("market_data", {})
    selected = state.get("yield_data", {}).get("selected", {})

    fallback = (
        f"For {crop} in {location}: risk score {risk}. "
        f"Yield index {selected.get('yield_index', 'N/A')}, "
        f"price trend {market.get('price_trend', 'unknown')}. "
        f"Recommended action: {'Sell/Hedge' if risk >= 0.75 else 'Monitor and hold'}"
    )

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key or ChatOpenAI is None:
        return {"final_advisory": fallback}

    model = ChatOpenAI(
        model=os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
        api_key=api_key,
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        temperature=0.2,
        default_headers={
            "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "http://localhost"),
            "X-Title": os.getenv("OPENROUTER_APP_NAME", "AgriIntel"),
        },
    )

    prompt = (
        "You are an agricultural risk advisor. "
        "Write a concise recommendation in plain English (max 120 words).\n"
        f"crop={crop}, location={location}, risk={risk}, "
        f"yield_index={selected.get('yield_index')}, "
        f"price_trend={market.get('price_trend')}, latest_price={market.get('latest_price_usd_mt')}, "
        f"heat_risk={state.get('climate_data', {}).get('heat_risk')}, dry_risk={state.get('climate_data', {}).get('dry_risk')}"
    )

    try:
        advisory = model.invoke(prompt)
        content = advisory.content if hasattr(advisory, "content") else str(advisory)
        text = content.strip() if isinstance(content, str) else str(content)
        return {"final_advisory": text or fallback}
    except Exception:
        return {"final_advisory": fallback}
