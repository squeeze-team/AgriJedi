from __future__ import annotations

import json
import logging
import math
import os
import re
from contextlib import contextmanager
from urllib.parse import urlencode
from typing import Any, Callable, Dict, List, Literal, TypedDict
from datetime import datetime, timedelta

try:
    import httpx
except ImportError:
    httpx = None

try:
    import openmeteo_requests
except ImportError:
    openmeteo_requests = None

try:
    import requests_cache
except ImportError:
    requests_cache = None

try:
    from retry_requests import retry
except ImportError:
    retry = None

try:
    from pydantic import BaseModel, ConfigDict
except ImportError:
    ConfigDict = dict

    class BaseModel:
        def __init__(self, **data: Any) -> None:
            for key, value in data.items():
                setattr(self, key, value)

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> bool:
        return False

try:
    from langgraph.graph import END, START, StateGraph

except ImportError:
    END = "__end__"
    START = "__start__"
    StateGraph = None


class CropHealthData(TypedDict, total=False):
    ndvi: float
    leaf_area_index: float
    status: str
    selected_crop_group: str
    selected_crop_label: str
    yield_index: float
    yield_index_label: str
    predicted_yield_t_ha: float
    target_year: int
    confidence: float
    anomaly_vs_5yr_pct: float
    estimated_yield_delta_pct: float
    satellite_history_signal: str
    latest_scene_date: str
    cloud_cover_pct: float
    cropland_coverage_pct: float
    segmented_area_ha: float
    source: str


class WeatherForecast(TypedDict, total=False):
    days: int
    source: str
    soil_moisture_pct: float
    precipitation_mm: float
    flood_risk: float
    heat_risk: float
    weather_risk_score: float
    extreme_event: str | None


class BioMonitorReport(TypedDict, total=False):
    risk_score: float
    phenology_stage: str
    mitigation: str
    alert_code: str
    stress_summary: str
    critical_growth_stage: bool


class AlertDispatch(TypedDict, total=False):
    channel: str
    message: str
    dispatched: bool


class QueryAnalysisResult(TypedDict, total=False):
    field_name: str | None
    need_geo: bool
    bbox: List[float]
    crop_type: str
    analysis_report: str


class AgriState(TypedDict, total=False):
    user_query: str
    field_name: str | None
    need_geo: bool
    requested_api_nodes: List[str]
    api_routing_summary: str
    location_name: str
    crop_type: str
    query_analysis_report: str
    query_analysis_debug: str
    query_analysis_error: str
    query_validation_status: str
    geocode_status: str
    geocode_error: str
    needs_clarification: bool
    clarification_message: str
    country_code: str
    run_mode: str
    bbox: List[float]
    geocode_debug: str
    api_router_source: str
    api_router_reason: str
    yield_analysis_data: Dict[str, Any]
    yield_analysis_debug: str
    yield_analysis_error: str
    market_overview_data: Dict[str, Any]
    market_overview_debug: str
    market_overview_error: str
    crop_report_data: Dict[str, Any]
    crop_report_debug: str
    crop_report_error: str
    market_focus_crop: str
    market_price_stats: Dict[str, Any]
    crop_health_data: CropHealthData
    weather_risk_score: float
    weather_forecast: WeatherForecast
    weather_debug: str
    weather_error: str
    bio_monitor: BioMonitorReport
    phenology_stage: str
    final_advisory: str
    orchestrator_debug: str
    orchestrator_error: str
    is_emergency: bool
    emergency_dispatch: AlertDispatch


class AgentPrompt(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: str
    context: str
    prompt: str


class ApiConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    geocoding: str
    yield_analysis: str
    market_overview: str
    crop_report: str
    weather: str


def create_http_client(
    timeout_seconds: float | None = None,
    headers: Dict[str, str] | None = None,
):
    if httpx is None:
        raise RuntimeError(
            "httpx is not installed. Install dependencies with "
            "`python3 -m pip install -r requirements.txt`."
        )

    client_cls = getattr(httpx, "Client", None)
    if not callable(client_cls):
        raise RuntimeError("httpx.Client is not available in the installed httpx module.")

    candidates: List[Dict[str, Any]] = []
    if timeout_seconds is not None and headers:
        candidates.append({"timeout": timeout_seconds, "headers": headers})
    if timeout_seconds is not None:
        candidates.append({"timeout": timeout_seconds})
    if headers:
        candidates.append({"headers": headers})
    candidates.append({})

    for kwargs in candidates:
        try:
            return client_cls(**kwargs)
        except TypeError:
            continue

    raise RuntimeError("http_client_init_signature_mismatch")


@contextmanager
def managed_http_client(
    timeout_seconds: float | None = None,
    headers: Dict[str, str] | None = None,
):
    client = create_http_client(timeout_seconds=timeout_seconds, headers=headers)
    try:
        yield client
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def safe_raise_for_status(response: Any) -> None:
    method = getattr(response, "raise_for_status", None)
    if callable(method):
        method()
        return

    status_code = parse_float(getattr(response, "status_code", 200))
    if status_code is not None and status_code >= 400:
        raise RuntimeError(f"http_error_{int(status_code)}")


def http_request_with_fallbacks(
    client: Any,
    method: str,
    url: str,
    *,
    params: Dict[str, Any] | None = None,
    headers: Dict[str, str] | None = None,
    json_body: Dict[str, Any] | None = None,
):
    method_lower = method.lower()
    request_fn = getattr(client, method_lower, None)
    serialized_json = json.dumps(json_body) if json_body is not None else None

    def try_call(callable_fn: Any, args: List[Any], kwargs_variants: List[Dict[str, Any]]):
        for kwargs in kwargs_variants:
            try:
                return callable_fn(*args, **kwargs)
            except TypeError:
                continue
        return None

    if callable(request_fn):
        request_variants: List[Dict[str, Any]] = []
        base: Dict[str, Any] = {}
        if params:
            base["params"] = params
        if headers:
            base["headers"] = headers
        if json_body is not None:
            request_variants.append({**base, "json": json_body})
            request_variants.append({
                **base,
                "content": serialized_json,
                "headers": {**(headers or {}), "Content-Type": "application/json"},
            })
        request_variants.append(base)
        request_variants.append({})
        response = try_call(request_fn, [url], request_variants)
        if response is not None:
            return response

    request_any = getattr(client, "request", None)
    if callable(request_any):
        request_variants_any: List[Dict[str, Any]] = []
        base_any: Dict[str, Any] = {}
        if params:
            base_any["params"] = params
        if headers:
            base_any["headers"] = headers
        if json_body is not None:
            request_variants_any.append({**base_any, "json": json_body})
            request_variants_any.append({
                **base_any,
                "content": serialized_json,
                "headers": {**(headers or {}), "Content-Type": "application/json"},
            })
        request_variants_any.append(base_any)
        request_variants_any.append({})
        response = try_call(request_any, [method_upper(method), url], request_variants_any)
        if response is not None:
            return response

    url_with_params = url
    if params:
        query = urlencode(params)
        joiner = "&" if "?" in url else "?"
        url_with_params = f"{url}{joiner}{query}"

    kwargs_variants_final: List[Dict[str, Any]] = []
    if headers and json_body is not None:
        kwargs_variants_final.append({
            "headers": {**headers, "Content-Type": "application/json"},
            "content": serialized_json,
        })
    elif headers:
        kwargs_variants_final.append({"headers": headers})
    elif json_body is not None:
        kwargs_variants_final.append({
            "headers": {"Content-Type": "application/json"},
            "content": serialized_json,
        })
    kwargs_variants_final.append({})

    if callable(request_fn):
        response = try_call(request_fn, [url_with_params], kwargs_variants_final)
        if response is not None:
            return response
    if callable(request_any):
        response = try_call(request_any, [method_upper(method), url_with_params], kwargs_variants_final)
        if response is not None:
            return response

    raise RuntimeError("http_request_signature_mismatch")


def method_upper(method: str) -> str:
    return method.strip().upper()


class FranceApiAdapters(BaseModel):
    model_config = ConfigDict(frozen=True)

    config: ApiConfig
    timeout_seconds: float = 120.0
    user_agent: str = "AgroMind/0.1"

    def build_client(self):
        return create_http_client(
            timeout_seconds=self.timeout_seconds,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
        )

    def geocode_with_nominatim(self, location_name: str) -> Dict[str, Any] | None:
        with managed_http_client(
            timeout_seconds=self.timeout_seconds,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
        ) as client:
            response = http_request_with_fallbacks(
                client,
                "GET",
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q": location_name,
                    "format": "jsonv2",
                    "limit": 1,
                    "addressdetails": 1,
                    "countrycodes": "fr",
                },
            )
            safe_raise_for_status(response)
            payload = response.json()

        if not payload:
            return None

        top_result = payload[0]
        bbox = top_result.get("boundingbox")
        address = top_result.get("address", {})
        if not bbox or address.get("country_code", "").lower() != "fr":
            return None

        min_lat, max_lat, min_lon, max_lon = [float(value) for value in bbox]
        return {
            "country_code": "FR",
            "bbox": [
                round(min_lon, 4),
                round(min_lat, 4),
                round(max_lon, 4),
                round(max_lat, 4),
            ],
        }

    def fetch_meteo_france_forecast(self, lat: float, lon: float) -> WeatherForecast | None:
        if (
            openmeteo_requests is None
            or requests_cache is None
            or retry is None
        ):
            return None

        cache_path = os.getenv("OPEN_METEO_CACHE_PATH", ".cache/openmeteo")
        cache_ttl = int(os.getenv("OPEN_METEO_CACHE_TTL_SECONDS", "3600"))
        forecast_url = os.getenv("OPEN_METEO_FORECAST_URL", "https://api.open-meteo.com/v1/forecast")
        bounding_box = os.getenv("OPEN_METEO_BOUNDING_BOX")

        cache_session = requests_cache.CachedSession(cache_path, expire_after=cache_ttl)
        retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
        client = openmeteo_requests.Client(session=retry_session)

        params: Dict[str, Any] = {
            "latitude": lat,
            "longitude": lon,
            "hourly": [
                "temperature_2m",
                "rain",
                "relative_humidity_2m",
                "wind_gusts_10m",
            ],
            "forecast_days": 14,
            "models": "meteofrance_seamless",
        }
        if bounding_box:
            params["bounding_box"] = bounding_box

        responses = client.weather_api(forecast_url, params=params)
        if not responses:
            return None

        response = responses[0]
        hourly = response.Hourly()
        variable_count = hourly.VariablesLength()
        if variable_count < 4:
            return None

        temperatures = finite_float_values(list(hourly.Variables(0).ValuesAsNumpy()))
        rainfall = finite_float_values(list(hourly.Variables(1).ValuesAsNumpy()))
        humidity = finite_float_values(list(hourly.Variables(2).ValuesAsNumpy()))
        gusts = finite_float_values(list(hourly.Variables(3).ValuesAsNumpy()))
        if not temperatures or not rainfall or not humidity:
            return None

        avg_humidity = round(float(sum(humidity) / max(len(humidity), 1)), 1)
        total_rain = round(float(sum(rainfall)), 1)
        avg_temp = round(float(sum(temperatures) / max(len(temperatures), 1)), 1)
        max_gust = round(float(max(gusts)) if gusts else 0.0, 1)

        flood_risk = round(clamp(0.16 + (total_rain * 0.01) + (max_gust / 300.0)), 2)
        heat_risk = round(clamp(0.2 + max(0.0, (26.0 - avg_temp)) * 0.015), 2)
        low_moisture_penalty = round(clamp(max(0.0, (35.0 - avg_humidity)) * 0.02), 2)
        weather_risk = round(clamp((heat_risk * 0.35) + (flood_risk * 0.35) + (low_moisture_penalty * 0.3)), 2)

        return {
            "days": 14,
            "source": f"{self.config.weather} via Open-Meteo",
            "soil_moisture_pct": avg_humidity,
            "precipitation_mm": total_rain,
            "flood_risk": flood_risk,
            "heat_risk": heat_risk,
            "extreme_event": "100-year Flood" if flood_risk >= 0.85 else None,
            "weather_risk_score": weather_risk,
        }

    def search_yield_analysis(
        self,
        bbox: List[float],
        date_range: str | None = None,
    ) -> Dict[str, Any] | None:
        if httpx is None:
            return None

        yield_analysis_url = os.getenv(
            "YIELD_ANALYSIS_URL",
            "http://localhost:8000/agent/yield-analysis",
        )

        if not date_range:
            window_days_raw = os.getenv("YIELD_ANALYSIS_LOOKBACK_DAYS", "92")
            try:
                window_days = int(window_days_raw)
            except (TypeError, ValueError):
                window_days = 92
            end = datetime.now().date()
            start = end - timedelta(days=max(window_days, 1))
            date_range = f"{start.isoformat()}/{end.isoformat()}"

        with managed_http_client(
            timeout_seconds=self.timeout_seconds,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
        ) as client:
            response = http_request_with_fallbacks(
                client,
                "POST",
                yield_analysis_url,
                json_body={"bbox": bbox, "date": date_range},
            )
            safe_raise_for_status(response)
            payload = response.json()

        if isinstance(payload, dict):
            return payload
        return None

    def search_market_overview(
        self,
        start: str | None = None,
        end: str | None = None,
    ) -> Dict[str, Any] | None:
        if httpx is None:
            return None

        market_overview_url = os.getenv(
            "MARKET_OVERVIEW_URL",
            "http://localhost:8000/agent/market-overview",
        )

        if not end:
            end = datetime.now().strftime("%Y%m%d")
        if not start:
            range_days_raw = os.getenv("MARKET_TIME_RANGE", "365")
            try:
                range_days = int(range_days_raw)
            except (TypeError, ValueError):
                range_days = 365
            start = (datetime.now() - timedelta(days=max(range_days, 1))).strftime("%Y%m%d")

        with managed_http_client(
            timeout_seconds=self.timeout_seconds,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
        ) as client:
            response = http_request_with_fallbacks(
                client,
                "POST",
                market_overview_url,
                json_body={"start": start, "end": end},
            )
            safe_raise_for_status(response)
            payload = response.json()

        if isinstance(payload, dict):
            return payload
        return None

    def search_crop_report(self, crop: str) -> Dict[str, Any] | None:
        if httpx is None:
            return None

        crop_report_url = os.getenv(
            "CROP_REPORT_URL",
            "http://localhost:8000/agent/crop-report",
        )

        with managed_http_client(
            timeout_seconds=self.timeout_seconds,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
        ) as client:
            response = http_request_with_fallbacks(
                client,
                "POST",
                crop_report_url,
                json_body={"crop": crop},
            )
            safe_raise_for_status(response)
            payload = response.json()

        if isinstance(payload, dict):
            return payload
        return None

API_CONFIG = ApiConfig(
    geocoding="OpenStreetMap Nominatim",
    yield_analysis="AgriIntel /agent/yield-analysis",
    market_overview="AgriIntel /agent/market-overview",
    crop_report="AgriIntel /agent/crop-report",
    weather="Meteo-France",
)

load_dotenv()

API_ADAPTERS = FranceApiAdapters(config=API_CONFIG)

LOGGER = logging.getLogger("agromind")
if not LOGGER.handlers:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    LOGGER.setLevel(level)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.propagate = False


AGENT_PROMPTS: Dict[str, AgentPrompt] = {
    "query_analysis_agent": AgentPrompt(
        role="Agricultural Query Analyst",
        context="You extract farm location mode (field-name which is used by OpenStreetMap or bbox - [min_lon,min_lat,max_lon,max_lat]) and crop from user text.",
        prompt=(
            "Extract field_name, need_geo, bbox, crop_type, and a concise analysis report from the user query."
        ),
    ),
    "geocoding_agent": AgentPrompt(
        role="Geospatial Intake Analyst",
        context="You convert a user-requested French area into a normalized bbox.",
        prompt=(
            "Use OpenStreetMap Nominatim search results to resolve the requested "
            "French area, extract the bbox, and reject non-French locations."
        ),
    ),
    "yield_analysis_agent": AgentPrompt(
        role="Yield Analysis Specialist",
        context="You use backend /agent/yield-analysis output to assess crop NDVI and yield outlook.",
        prompt=(
            "Select the crop group that best matches query crop_type, then extract NDVI, "
            "yield index, and yield forecast confidence."
        ),
    ),
    "market_overview_agent": AgentPrompt(
        role="Market Overview Specialist",
        context="You use backend /agent/market-overview output for crop price and weather trends.",
        prompt=(
            "Select the market crop that best matches query crop_type and extract price trend signals."
        ),
    ),
    "crop_report_agent": AgentPrompt(
        role="Crop Financial Intelligence Specialist",
        context="You use backend /agent/crop-report markdown to enrich crop-specific financial context.",
        prompt=(
            "Fetch crop report markdown for wheat/corn/grape when available and pass it to the orchestrator."
        ),
    ),
    "climate_agent": AgentPrompt(
        role="Agroclimate Risk Forecaster",
        context="You use Meteo-France forecast data for French agricultural zones.",
        prompt=(
            "Assess 14-day weather risk from Meteo-France data, emphasizing soil "
            "moisture, precipitation, and flood risk."
        ),
    ),
    "bio_monitor": AgentPrompt(
        role="Senior Agronomist & Phenology Specialist",
        context="You receive NDVI/yield signals plus Meteo-France weather risk features.",
        prompt=(
            "Analyze NDVI against crop stage. If stage is Flowering or Grain "
            "Filling and moisture < 20%, flag CRITICAL_DROUGHT_RISK. "
            "Differentiate natural senescence from disease using vegetation history."
        ),
    ),
    "orchestrator": AgentPrompt(
        role="Agricultural Operations Orchestrator",
        context="You reconcile user intent with yield outlook, market trend, and weather risk.",
        prompt=(
            "Perform self-correction. If biological and weather risk are severe, "
            "override toward risk reduction."
        ),
    ),
}

AGROMIND_IDENTITY = (
    "You are AgroMind, an agricultural intelligence and operations assistant. "
    "Provide reliable, evidence-based guidance using only supplied inputs."
)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def parse_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def finite_float_values(values: List[Any]) -> List[float]:
    cleaned: List[float] = []
    for value in values:
        parsed = parse_float(value)
        if parsed is None:
            continue
        if parsed != parsed:
            continue
        cleaned.append(parsed)
    return cleaned


def exception_to_error_code(prefix: str, exc: Exception) -> str:
    detail = type(exc).__name__
    if isinstance(exc, RuntimeError):
        runtime_msg = str(exc)
        if "http_request_signature_mismatch" in runtime_msg:
            detail = "http_request_signature_mismatch"
        elif "http_client_init_signature_mismatch" in runtime_msg:
            detail = "http_client_init_signature_mismatch"
    if httpx is not None:
        http_status_error = getattr(httpx, "HTTPStatusError", None)
        connect_error = getattr(httpx, "ConnectError", None)
        timeout_error = getattr(httpx, "TimeoutException", None)
        if isinstance(http_status_error, type) and isinstance(exc, http_status_error):
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
            detail = f"http_{status_code}" if status_code is not None else "http_error"
        elif isinstance(connect_error, type) and isinstance(exc, connect_error):
            detail = "connect_error"
        elif isinstance(timeout_error, type) and isinstance(exc, timeout_error):
            detail = "timeout"
    return f"{prefix}:{detail}"


def parse_json_object_from_text(text: str) -> Dict[str, Any] | None:
    stripped = text.strip()
    fenced_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", stripped, flags=re.IGNORECASE)
    if fenced_match:
        candidate = fenced_match.group(1).strip()
        try:
            payload = json.loads(candidate)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass

    try:
        payload = json.loads(stripped)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        payload = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def infer_crop_type_from_query(user_query: str, fallback_crop: str) -> str:
    query = user_query.lower()
    crop_aliases = [
        "wheat",
        "maize",
        "corn",
        "grape",
        "vineyard",
        "barley",
        "soy",
        "soybean",
        "coffee",
        "sugar",
        "cotton",
    ]
    for crop in crop_aliases:
        if crop in query:
            return crop
    return fallback_crop


def normalize_crop_type(crop: str) -> str:
    aliases = {
        "corn": "maize",
        "soybean": "soy",
        "grapes": "grape",
        "vineyard": "grape",
        "vineyards": "grape",
        "wine": "grape",
    }
    value = crop.strip().lower()
    if not value:
        return "wheat"
    return aliases.get(value, value)


def map_crop_type_to_yield_group(crop_type: str) -> str:
    crop = normalize_crop_type(crop_type)
    mapping = {
        "wheat": "wheat",
        "maize": "maize",
        "grape": "grape",
        "barley": "other_cereal",
        "oat": "other_cereal",
        "oats": "other_cereal",
        "rye": "other_cereal",
        "soy": "other",
        "coffee": "other",
        "sugar": "other",
        "cotton": "other",
    }
    return mapping.get(crop, "other")


def map_crop_type_to_market_crop(crop_type: str) -> str:
    crop = normalize_crop_type(crop_type)
    if crop == "maize":
        return "maize"
    if crop == "grape":
        return "grape"
    return "wheat"


def map_crop_type_to_report_crop(crop_type: str) -> str | None:
    crop = normalize_crop_type(crop_type)
    if crop == "wheat":
        return "wheat"
    if crop == "maize":
        return "corn"
    if crop == "grape":
        return "grape"
    return None


API_NODE_ORDER: List[str] = [
    "yield_analysis_agent",
    "market_overview_agent",
    "crop_report_agent",
    "climate_agent",
]

API_NODES_REQUIRING_GEO = {"yield_analysis_agent", "climate_agent"}


def normalize_requested_api_nodes(raw_nodes: Any) -> List[str]:
    if not isinstance(raw_nodes, list):
        return []
    normalized: List[str] = []
    for node in raw_nodes:
        node_name = str(node or "").strip()
        if node_name in API_NODE_ORDER and node_name not in normalized:
            normalized.append(node_name)
    return normalized


def infer_requested_api_nodes_fallback(
    user_query: str,
    crop_type: str,
    run_mode: str,
) -> List[str]:
    if normalize_run_mode(run_mode) == "analysis":
        return list(API_NODE_ORDER)

    query = user_query.lower()

    def has_any_token(tokens: List[str]) -> bool:
        for token in tokens:
            if re.search(rf"\b{re.escape(token)}\b", query):
                return True
        return False

    has_any_data_intent = has_any_token(
        [
            "risk",
            "assess",
            "analysis",
            "strategy",
            "overview",
            "recommend",
            "advice",
            "yield",
            "ndvi",
            "market",
            "price",
            "weather",
            "climate",
            "financial",
            "report",
        ]
    )
    only_weather = bool(re.search(r"\bonly\b.*\b(weather|climate|rain|temperature|moisture)\b", query))
    only_market = bool(re.search(r"\bonly\b.*\b(market|price|financial|commodity)\b", query))
    only_yield = bool(re.search(r"\bonly\b.*\b(yield|ndvi|vegetation|crop detection)\b", query))

    if only_weather:
        return ["climate_agent"]
    if only_market:
        nodes = ["market_overview_agent"]
        if map_crop_type_to_report_crop(crop_type):
            nodes.append("crop_report_agent")
        return nodes
    if only_yield:
        return ["yield_analysis_agent"]

    wants_yield = has_any_token(["yield", "ndvi", "vegetation", "crop health", "crop detect", "biomonitor"])
    wants_market = has_any_token(["market", "price", "sell", "hold", "trade", "financial", "commodity"])
    wants_weather = has_any_token(
        ["weather", "climate", "rain", "temperature", "heat", "flood", "drought", "moisture"]
    )
    wants_report = has_any_token(["report", "markdown", "outlook", "fundamental", "finance note"])
    if wants_market or has_any_token(["financial analysis", "financial overview"]):
        wants_report = True
    if has_any_token(["risk"]) and not (wants_yield or wants_weather):
        wants_yield = True
        wants_weather = True

    selected: List[str] = []
    if wants_yield:
        selected.append("yield_analysis_agent")
    if wants_market:
        selected.append("market_overview_agent")
    if wants_report and map_crop_type_to_report_crop(crop_type):
        selected.append("crop_report_agent")
    if wants_weather:
        selected.append("climate_agent")

    if not selected:
        if has_any_data_intent:
            return list(API_NODE_ORDER)
        return []

    return normalize_requested_api_nodes(selected)


def build_llm_api_router_decision(
    user_query: str,
    crop_type: str,
) -> Dict[str, Any] | None:
    if httpx is None:
        return None

    endpoint, api_key = resolve_llm_endpoint_and_key()
    if not api_key:
        return None

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    timeout_seconds = parse_float(os.getenv("OPENAI_TIMEOUT_SECONDS", "25")) or 25.0
    report_crop = map_crop_type_to_report_crop(crop_type)
    report_available = report_crop is not None
    report_note = (
        f"available (maps to '{report_crop}')"
        if report_available
        else "not available for this crop"
    )

    system_prompt = (
        f"{AGROMIND_IDENTITY}\n"
        "You are an API routing planner for an agriculture assistant.\n"
        "Choose the minimum set of APIs needed to answer the user query.\n"
        "Allowed API nodes:\n"
        "- yield_analysis_agent: NDVI, crop detection in bbox/date, yield index, vegetation assessment.\n"
        "- market_overview_agent: commodity price, trend, period change.\n"
        "- crop_report_agent: markdown financial report (only for wheat/maize/grape families).\n"
        "- climate_agent: weather risk, moisture, precipitation, heat/flood risk.\n"
        "Return strict JSON only with keys:\n"
        "1) reason: short sentence\n"
        "2) requested_api_nodes: array of node names from the allowed list\n"
        "Rules:\n"
        "- Prefer minimal APIs.\n"
        "- If the query asks full risk/strategy/overall assessment, include all 4 nodes.\n"
        "- If query is general chat without data need, return empty array.\n"
        "- Do not include unavailable crop_report_agent when report is not available."
    )
    user_prompt = (
        f"user_query: {user_query}\n"
        f"crop_type: {crop_type}\n"
        f"crop_report_agent for this crop: {report_note}\n"
        f"allowed_nodes: {API_NODE_ORDER}"
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with managed_http_client(timeout_seconds=timeout_seconds) as client:
        response = http_request_with_fallbacks(
            client,
            "POST",
            endpoint,
            headers=headers,
            json_body={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.0,
            },
        )
        safe_raise_for_status(response)
        payload = response.json()

    choices = payload.get("choices", []) if isinstance(payload, dict) else []
    if not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message", {})
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        return None

    parsed = parse_json_object_from_text(content)
    if not isinstance(parsed, dict):
        return None

    requested_nodes = normalize_requested_api_nodes(parsed.get("requested_api_nodes"))
    if not report_available:
        requested_nodes = [node for node in requested_nodes if node != "crop_report_agent"]

    reason = str(parsed.get("reason") or "").strip()
    return {
        "requested_api_nodes": requested_nodes,
        "reason": reason or "llm_api_routing",
    }


def infer_requested_api_nodes(
    user_query: str,
    crop_type: str,
    run_mode: str,
) -> Dict[str, Any]:
    mode = normalize_run_mode(run_mode)
    if mode == "analysis":
        all_nodes = list(API_NODE_ORDER)
        reason = "analysis mode requires full pipeline"
        LOGGER.info(
            "api_router mode=%s source=%s requested_api_nodes=%s reason=%s",
            mode,
            "analysis_default",
            all_nodes,
            reason,
        )
        return {
            "requested_api_nodes": all_nodes,
            "api_router_source": "analysis_default",
            "api_router_reason": reason,
            "api_routing_summary": f"mode={mode}; router=analysis_default; selected_api_nodes={all_nodes}; reason={reason}",
        }

    llm_error = ""
    try:
        llm_result = build_llm_api_router_decision(user_query, crop_type)
    except Exception as exc:
        llm_result = None
        llm_error = exception_to_error_code("api_router_llm", exc)

    if isinstance(llm_result, dict):
        requested = normalize_requested_api_nodes(llm_result.get("requested_api_nodes"))
        reason = str(llm_result.get("reason") or "llm_api_routing")
        LOGGER.info(
            "api_router mode=%s source=%s requested_api_nodes=%s reason=%s",
            mode,
            "llm",
            requested,
            reason,
        )
        return {
            "requested_api_nodes": requested,
            "api_router_source": "llm",
            "api_router_reason": reason,
            "api_routing_summary": f"mode={mode}; router=llm; selected_api_nodes={requested}; reason={reason}",
        }

    fallback_nodes = infer_requested_api_nodes_fallback(user_query, crop_type, run_mode)
    if llm_error:
        reason = llm_error
        LOGGER.info(
            "api_router mode=%s source=%s requested_api_nodes=%s reason=%s",
            mode,
            "fallback",
            fallback_nodes,
            reason,
        )
        return {
            "requested_api_nodes": fallback_nodes,
            "api_router_source": "fallback",
            "api_router_reason": reason,
            "api_routing_summary": f"mode={mode}; router=fallback; selected_api_nodes={fallback_nodes}; llm_error={llm_error}",
        }
    reason = "invalid_response_or_not_configured"
    LOGGER.info(
        "api_router mode=%s source=%s requested_api_nodes=%s reason=%s",
        mode,
        "fallback",
        fallback_nodes,
        reason,
    )
    return {
        "requested_api_nodes": fallback_nodes,
        "api_router_source": "fallback",
        "api_router_reason": reason,
        "api_routing_summary": (
            f"mode={mode}; router=fallback; selected_api_nodes={fallback_nodes}; "
            "llm_status=invalid_response_or_not_configured"
        ),
    }


def should_run_api_node(state: AgriState, node_name: str) -> bool:
    mode = normalize_run_mode(state.get("run_mode", "chat"))
    if mode == "analysis":
        return True
    requested = normalize_requested_api_nodes(state.get("requested_api_nodes"))
    if not requested:
        return False
    return node_name in requested


def selected_api_nodes_need_geocoding(state: AgriState) -> bool:
    requested = normalize_requested_api_nodes(state.get("requested_api_nodes"))
    if not requested:
        return False
    return any(node in API_NODES_REQUIRING_GEO for node in requested)


def parse_env_int(var_name: str, default: int) -> int:
    raw = os.getenv(var_name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def resolve_llm_endpoint_and_key() -> tuple[str, str | None]:
    endpoint = os.getenv("OPENAI_API_URL", "https://api.openai.com/v1/chat/completions").strip()
    api_key = os.getenv("OPENAI_API_KEY")
    return endpoint, api_key


def normalize_location_name(location: str) -> str:
    value = re.sub(r"\s+", " ", location.strip().strip(",")).strip()
    if not value:
        return value
    lowered = value.lower()
    canonical = re.sub(r"[^a-z0-9 ]+", " ", lowered)
    canonical = re.sub(r"\s+", " ", canonical).strip()
    aliases = {
        "beauce": "Chartres, Eure-et-Loir, France",
        "beauce france": "Chartres, Eure-et-Loir, France",
        "ile de france": "Paris, France",
        "ile-de-france": "Paris, France",
        "idf": "Paris, France",
        "provence": "Aix-en-Provence, France",
        "brittany": "Rennes, France",
        "normandy": "Rouen, France",
        "champagne": "Reims, France",
        "bordeaux": "Bordeaux, France",
        "rhone valley": "Rhone Valley, France"
    }
    if canonical in aliases:
        return aliases[canonical]
    if "france" not in lowered:
        return f"{value}, France"
    return value


def geocode_candidates(field_name: str) -> List[str]:
    normalized = normalize_location_name(field_name)
    candidates: List[str] = []
    if normalized:
        candidates.append(normalized)
    if field_name and field_name not in candidates:
        candidates.append(field_name)

    # Keep order, remove empties and duplicates.
    ordered: List[str] = []
    seen = set()
    for item in candidates:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(item.strip())
    return ordered[:4]


def known_bbox_for_location(location_name: str) -> Dict[str, Any] | None:
    normalized = normalize_location_name(location_name).strip().lower()
    canonical = re.sub(r"[^a-z0-9 ]+", " ", normalized)
    canonical = re.sub(r"\s+", " ", canonical).strip()
    presets: Dict[str, List[float]] = {
        "chartres eure et loir france": [1.2, 48.0, 1.8, 48.4],  # Beauce
        "chartres france": [1.2, 48.0, 1.8, 48.4],
        "beauce": [1.2, 48.0, 1.8, 48.4],
        "paris france": [2.22, 48.80, 2.47, 48.92],
        "aix en provence france": [5.30, 43.45, 5.55, 43.62],
        "rennes france": [-1.79, 48.03, -1.57, 48.20],
        "rouen france": [1.00, 49.35, 1.20, 49.50],
        "reims france": [3.80, 49.10, 4.00, 49.30],
        "bordeaux france": [-0.60, 44.80, -0.40, 44.90],
        "rhone valley france": [4.67, 44.71, 4.97, 45.01],
    }
    bbox = presets.get(canonical)
    if not bbox:
        return None
    return {
        "country_code": "FR",
        "bbox": bbox,
        "geocode_debug": f"preset_bbox:{canonical}",
    }


def extract_lat_lon_from_text(text: str) -> List[float] | None:
    compact = re.sub(r"\s+", " ", text.strip())
    patterns = [
        r"lat(?:itude)?\s*[:=]?\s*(-?\d+(?:\.\d+)?)\s*[, ]+\s*lon(?:gitude)?\s*[:=]?\s*(-?\d+(?:\.\d+)?)",
        r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if not match:
            continue
        lat = parse_float(match.group(1))
        lon = parse_float(match.group(2))
        if lat is None or lon is None:
            continue
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return [round(lat, 6), round(lon, 6)]
    return None


def normalize_bbox(bbox_raw: Any) -> List[float] | None:
    if not isinstance(bbox_raw, list) or len(bbox_raw) < 4:
        return None
    min_lon = parse_float(bbox_raw[0])
    min_lat = parse_float(bbox_raw[1])
    max_lon = parse_float(bbox_raw[2])
    max_lat = parse_float(bbox_raw[3])
    if None in {min_lon, min_lat, max_lon, max_lat}:
        return None
    if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180):
        return None
    if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
        return None
    if max_lon <= min_lon or max_lat <= min_lat:
        return None
    return [
        round(min_lon, 4),
        round(min_lat, 4),
        round(max_lon, 4),
        round(max_lat, 4),
    ]


def extract_bbox_from_text(text: str) -> List[float] | None:
    compact = re.sub(r"\s+", " ", text.strip())
    patterns = [
        r"\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]",
        r"\bbbox\b\s*(?:=|:)?\s*(-?\d+(?:\.\d+)?)\s*[, ]+\s*(-?\d+(?:\.\d+)?)\s*[, ]+\s*(-?\d+(?:\.\d+)?)\s*[, ]+\s*(-?\d+(?:\.\d+)?)",
        r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = [
            parse_float(match.group(1)),
            parse_float(match.group(2)),
            parse_float(match.group(3)),
            parse_float(match.group(4)),
        ]
        normalized = normalize_bbox(candidate)
        if normalized:
            return normalized
    return None


def bbox_from_center_lat_lon(center_lat: float, center_lon: float) -> List[float]:
    half_size = parse_float(os.getenv("GEO_FIXED_HALF_SIZE_DEG", "0.1")) or 0.1
    min_lon = round(center_lon - half_size, 4)
    min_lat = round(center_lat - half_size, 4)
    max_lon = round(center_lon + half_size, 4)
    max_lat = round(center_lat + half_size, 4)
    return [min_lon, min_lat, max_lon, max_lat]


def bbox_area_hectares(bbox: List[float]) -> float:
    west, south, east, north = bbox
    mid_lat_rad = math.radians((south + north) / 2)
    width_km = abs(east - west) * 111.32 * max(math.cos(mid_lat_rad), 0.1)
    height_km = abs(north - south) * 110.57
    return max(width_km * height_km * 100.0, 1.0)


def fallback_query_analysis(
    user_query: str,
    fallback_crop: str,
) -> QueryAnalysisResult:
    query = user_query.strip()
    crop = normalize_crop_type(infer_crop_type_from_query(query, fallback_crop))
    parsed_bbox = extract_bbox_from_text(query)
    if parsed_bbox:
        return {
            "field_name": None,
            "need_geo": False,
            "bbox": parsed_bbox,
            "crop_type": crop,
            "analysis_report": (
                f"Parsed bbox {parsed_bbox} from user query for crop {crop}. Geocoding skipped."
            ),
        }

    central = extract_lat_lon_from_text(query)
    if central:
        parsed_bbox = bbox_from_center_lat_lon(central[0], central[1])
        return {
            "field_name": None,
            "need_geo": False,
            "bbox": parsed_bbox,
            "crop_type": crop,
            "analysis_report": (
                f"Parsed center coordinates lat {central[0]}, lon {central[1]} and converted "
                f"to bbox {parsed_bbox} for crop {crop}. Geocoding skipped."
            ),
        }

    location = ""
    match = re.search(
        r"\b(?:near|in|at|around)\s+([A-Za-z0-9 .,'-]+)",
        query,
        flags=re.IGNORECASE,
    )
    if match:
        location = normalize_location_name(match.group(1).strip().rstrip("."))
    if not location:
        location = "Unknown Farm, France"

    return {
        "field_name": location,
        "need_geo": True,
        "crop_type": crop,
        "analysis_report": f"Parsed field name '{location}' and crop '{crop}' from user query.",
    }


def infer_field_name_from_query(user_query: str) -> str:
    fallback = fallback_query_analysis(user_query, "wheat")
    field_name = fallback.get("field_name")
    return (field_name or "").strip()


def build_llm_query_analysis(
    user_query: str,
    fallback_crop: str,
) -> QueryAnalysisResult | None:
    if httpx is None:
        return None

    endpoint, api_key = resolve_llm_endpoint_and_key()
    if not api_key:
        return None

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    timeout_seconds = parse_float(os.getenv("OPENAI_TIMEOUT_SECONDS", "25")) or 25.0

    system_prompt = (
        f"{AGROMIND_IDENTITY}\n"
        f"Role: {AGENT_PROMPTS['query_analysis_agent'].role}\n"
        f"Context: {AGENT_PROMPTS['query_analysis_agent'].context}\n"
        f"Instruction: {AGENT_PROMPTS['query_analysis_agent'].prompt}\n"
        "Return valid JSON only with keys: field_name, need_geo, bbox, crop_type, analysis_report. "
        "If query has bbox, set need_geo=false, field_name=null, and bbox=[min_lon,min_lat,max_lon,max_lat]. "
        "If query does not have coordinates, set need_geo=true and provide field_name."
    )
    user_prompt = (
        f"user_query: {user_query}\n"
        f"fallback_crop_type: {fallback_crop}"
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with managed_http_client(timeout_seconds=timeout_seconds) as client:
        response = http_request_with_fallbacks(
            client,
            "POST",
            endpoint,
            headers=headers,
            json_body={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.0,
            },
        )
        safe_raise_for_status(response)
        payload = response.json()

    choices = payload.get("choices", []) if isinstance(payload, dict) else []
    if not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message", {})
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        return None

    parsed = parse_json_object_from_text(content)
    if not parsed:
        return None

    crop_type = normalize_crop_type(str(parsed.get("crop_type") or "").strip().lower())
    field_name_raw = parsed.get("field_name")
    field_name = None if field_name_raw is None else normalize_location_name(str(field_name_raw).strip())
    need_geo = parse_bool(parsed.get("need_geo", True), default=True)
    bbox = normalize_bbox(parsed.get("bbox"))
    analysis_report = str(parsed.get("analysis_report") or "").strip()

    if not crop_type:
        crop_type = fallback_crop
    if not analysis_report:
        analysis_report = "Parsed query intent."

    if not need_geo:
        if not bbox:
            bbox = extract_bbox_from_text(user_query)
        if not bbox:
            central = extract_lat_lon_from_text(user_query)
            if central:
                bbox = bbox_from_center_lat_lon(central[0], central[1])
        if not bbox:
            return None
        return {
            "field_name": None,
            "need_geo": False,
            "bbox": bbox,
            "crop_type": crop_type,
            "analysis_report": analysis_report,
        }

    if not field_name:
        field_name = infer_field_name_from_query(user_query)
    if not field_name:
        return None
    return {
        "field_name": field_name,
        "need_geo": True,
        "crop_type": crop_type,
        "analysis_report": analysis_report,
    }


def query_analysis_node(state: AgriState) -> Dict[str, Any]:
    user_query = state.get("user_query", "")
    fallback_crop = state.get("crop_type", "wheat")
    run_mode = normalize_run_mode(state.get("run_mode", "chat"))
    llm_configured = bool(os.getenv("OPENAI_API_KEY"))

    llm_result = None
    query_error = ""
    try:
        llm_result = build_llm_query_analysis(user_query, fallback_crop)
    except Exception as exc:
        query_error = exception_to_error_code("query_analysis_llm", exc)

    if llm_result:
        routing_decision = infer_requested_api_nodes(
            user_query,
            llm_result["crop_type"],
            run_mode,
        )
        result: Dict[str, Any] = {
            "crop_type": llm_result["crop_type"],
            "query_analysis_report": llm_result["analysis_report"],
            "query_analysis_debug": "llm_query_analysis",
            "requested_api_nodes": routing_decision["requested_api_nodes"],
            "api_routing_summary": routing_decision["api_routing_summary"],
            "api_router_source": routing_decision["api_router_source"],
            "api_router_reason": routing_decision["api_router_reason"],
        }
        if llm_result.get("need_geo", True):
            result["need_geo"] = True
            result["field_name"] = llm_result.get("field_name")
        else:
            result["need_geo"] = False
            result["field_name"] = None
            result["bbox"] = llm_result["bbox"]
        return result

    fallback_result = fallback_query_analysis(user_query, fallback_crop)
    routing_decision = infer_requested_api_nodes(
        user_query,
        fallback_result["crop_type"],
        run_mode,
    )
    debug_reason = "fallback_query_analysis"
    if query_error:
        debug_reason = f"fallback_query_analysis_llm_error:{query_error}"
    elif llm_configured:
        debug_reason = "fallback_query_analysis_llm_invalid_response"

    result: Dict[str, Any] = {
        "crop_type": fallback_result["crop_type"],
        "query_analysis_report": fallback_result["analysis_report"],
        "query_analysis_debug": debug_reason,
        "requested_api_nodes": routing_decision["requested_api_nodes"],
        "api_routing_summary": routing_decision["api_routing_summary"],
        "api_router_source": routing_decision["api_router_source"],
        "api_router_reason": routing_decision["api_router_reason"],
        # Fallback succeeded, so keep query-analysis status non-failing.
        "query_analysis_error": "",
    }
    if fallback_result.get("need_geo", True):
        result["need_geo"] = True
        result["field_name"] = fallback_result.get("field_name")
    else:
        result["need_geo"] = False
        result["field_name"] = None
        result["bbox"] = fallback_result["bbox"]
    return result


def validation_node(state: AgriState) -> Dict[str, Any]:
    allowed_crops = {"wheat", "maize", "grape", "barley", "soy", "coffee", "sugar", "cotton"}
    crop_type = normalize_crop_type(state.get("crop_type", "wheat"))
    need_geo = bool(state.get("need_geo", True))
    field_name = (state.get("field_name") or "").strip()
    parsed_bbox = state.get("bbox") or []

    issues: List[str] = []
    if crop_type not in allowed_crops:
        issues.append(f"unsupported_crop_type:{crop_type}")
    if need_geo:
        if len(field_name) < 3:
            issues.append("field_name_missing_or_too_short")
    else:
        if normalize_bbox(parsed_bbox) is None:
            issues.append("bbox_missing_or_invalid")

    if issues:
        return {
            "crop_type": crop_type,
            "query_validation_status": "needs_clarification",
            "needs_clarification": True,
            "clarification_message": (
                "Need a clearer query before analysis. "
                f"Validation issues: {', '.join(issues)}."
            ),
        }

    response: Dict[str, Any] = {
        "crop_type": crop_type,
        "need_geo": need_geo,
        "query_validation_status": "validated",
        "needs_clarification": False,
    }
    if not need_geo:
        response["bbox"] = normalize_bbox(parsed_bbox)
    return response


def clarification_node(state: AgriState) -> Dict[str, Any]:
    clarification = state.get(
        "clarification_message",
        "Need more detail to continue.",
    )
    report = state.get("query_analysis_report", "No query-analysis report was produced.")
    user_query = state.get("user_query", "")
    field_name = state.get("field_name", "Unknown")
    need_geo = state.get("need_geo", True)
    parsed_bbox = state.get("bbox", [])
    crop_type = state.get("crop_type", "Unknown")
    return {
        "final_advisory": "\n".join(
            [
                "Analysis paused - clarification required.",
                f"User query: {user_query}",
                f"Parsed field_name: {field_name}",
                f"need_geo: {need_geo}",
                f"Parsed bbox: {parsed_bbox}",
                f"Parsed crop: {crop_type}",
                f"Query analysis report: {report}",
                f"Reason: {clarification}",
                "Please provide either a field/location name or an explicit bbox [min_lon,min_lat,max_lon,max_lat], plus crop type.",
            ]
        )
    }


def compose_orchestrator_facts(state: AgriState, final_action: str) -> str:
    forecast = state.get("weather_forecast", {})
    bio = state.get("bio_monitor", {})
    crop_health = state.get("crop_health_data", {})
    market_crop = state.get("market_focus_crop", "wheat")
    market_stats = state.get("market_price_stats", {})
    yield_data = state.get("yield_analysis_data", {})
    market_data = state.get("market_overview_data", {})
    crop_report_data = state.get("crop_report_data", {})
    crop_report_md = str(crop_report_data.get("report_markdown") or "").strip()
    requested_api_nodes = normalize_requested_api_nodes(state.get("requested_api_nodes"))
    return "\n".join(
        [
            f"User query: {state.get('user_query', '')}",
            f"Query analysis report: {state.get('query_analysis_report', 'n/a')}",
            f"Query analysis debug: {state.get('query_analysis_debug', 'n/a')}",
            f"API routing summary: {state.get('api_routing_summary', '')}",
            f"API router source: {state.get('api_router_source', '')}",
            f"API router reason: {state.get('api_router_reason', '')}",
            f"Selected API nodes: {requested_api_nodes}",
            f"Field name: {state.get('field_name')}",
            f"need_geo: {state.get('need_geo', True)}",
            f"parsed_bbox: {state.get('bbox') if not state.get('need_geo', True) else None}",
            f"Location: {state.get('location_name', 'n/a')} ({state.get('country_code', 'n/a')})",
            f"BBox: {state.get('bbox')}",
            f"Geocode debug: {state.get('geocode_debug', 'n/a')}",
            f"Crop: {state.get('crop_type', 'n/a')}",
            f"Yield selected crop group: {crop_health.get('selected_crop_group', 'n/a')}",
            f"Stage: {state.get('phenology_stage', 'n/a')}",
            (
                f"Yield source: {crop_health.get('source', 'n/a')} NDVI "
                f"{crop_health.get('ndvi')} yield_index {crop_health.get('yield_index')}"
            ),
            (
                f"Yield debug: {state.get('yield_analysis_debug', 'n/a')} | coverage "
                f"{crop_health.get('cropland_coverage_pct', 0)}% | area "
                f"{crop_health.get('segmented_area_ha', 0)} ha | confidence "
                f"{crop_health.get('confidence', 0)}"
            ),
            (
                f"Weather: {forecast.get('source', 'n/a')} risk {state.get('weather_risk_score')} "
                f"moisture {forecast.get('soil_moisture_pct')}%"
            ),
            f"Weather debug: {state.get('weather_debug', 'n/a')}",
            (
                f"Market crop: {market_crop} | latest price {market_stats.get('latest_price')} | "
                f"trend {market_stats.get('trend_direction')} | change {market_stats.get('period_change_pct')}%"
            ),
            f"Market debug: {state.get('market_overview_debug', 'n/a')}",
            (
                f"Crop report: {crop_report_data.get('crop', 'n/a')} | "
                f"source {crop_report_data.get('source', 'n/a')} | "
                f"chars {crop_report_data.get('report_char_count', 0)} | "
                f"truncated {crop_report_data.get('truncated', False)}"
            ),
            f"Crop report debug: {state.get('crop_report_debug', 'n/a')}",
            f"Crop report error: {state.get('crop_report_error', '')}",
            (
                f"Crop report summary: {crop_report_data.get('summary', '')}"
                if crop_report_data
                else "Crop report summary: "
            ),
            (
                f"Crop report markdown:\n{crop_report_md}"
                if crop_report_md
                else "Crop report markdown: "
            ),
            f"Yield summary: {yield_data.get('summary', '')}",
            f"Market summary: {market_data.get('summary', '')}",
            f"Recommended action: {final_action}",
            f"Mitigation: {bio.get('mitigation', 'n/a')}",
        ]
    )


def build_rule_based_advisory(
    state: AgriState,
    final_action: str,
    override_reason: str | None,
) -> str:
    lines = compose_orchestrator_facts(state, final_action).splitlines()
    if override_reason:
        lines.append(f"Override: {override_reason}")
    return "\n".join(lines)


def normalize_run_mode(mode: Any) -> Literal["chat", "analysis"]:
    value = str(mode or "").strip().lower()
    if value == "analysis":
        return "analysis"
    return "chat"


def crop_type_detected_in_bbox(state: AgriState) -> bool:
    crop_health = state.get("crop_health_data", {})
    yield_data = state.get("yield_analysis_data", {})
    selection_reason = str(yield_data.get("selection_reason") or "")
    if selection_reason == "skipped_by_query_router":
        return True
    status = str(crop_health.get("status") or "").strip().lower()
    label = str(crop_health.get("yield_index_label") or "").strip().lower()
    if selection_reason in {"requested_crop_not_detected", "query_profile_only_match"}:
        return False
    if "not detected" in status or "not detected" in label:
        return False
    return True


def infer_risk_score_1_to_5(state: AgriState) -> int:
    crop_health = state.get("crop_health_data", {})
    ndvi = clamp(parse_float(crop_health.get("ndvi")) or 0.6)
    weather_risk = clamp(parse_float(state.get("weather_risk_score")) or 0.0)
    combined = clamp((1.0 - ndvi) * 0.6 + weather_risk * 0.4)
    return int(max(1, min(5, round(1 + combined * 4))))


def infer_risk_triggers(state: AgriState, crop_in_bbox: bool) -> List[str] | None:
    if not crop_in_bbox:
        return None
    triggers: List[str] = []
    weather_risk = parse_float(state.get("weather_risk_score")) or 0.0
    market_stats = state.get("market_price_stats", {})
    trend = str(market_stats.get("trend_direction") or "stable")
    change = parse_float(market_stats.get("period_change_pct"))
    crop_health = state.get("crop_health_data", {})
    ndvi = parse_float(crop_health.get("ndvi")) or 0.0
    stage = str(state.get("phenology_stage") or "Unknown")
    moisture = parse_float(state.get("weather_forecast", {}).get("soil_moisture_pct"))

    if weather_risk >= 0.7:
        triggers.append("High weather-risk score (heat/flood stress regime).")
    if moisture is not None and moisture < 20:
        triggers.append("Low soil-moisture signal (<20%) during growth window.")
    if ndvi < 0.5:
        triggers.append("Weak NDVI canopy signal.")
    if stage in {"Flowering", "Grain Filling"}:
        triggers.append("Critical phenology stage sensitivity (flowering/grain filling).")
    if trend == "falling" and change is not None and change <= -10:
        triggers.append("Downward market trend with meaningful price drawdown.")
    if not triggers:
        triggers.append("No acute trigger; continue routine monitoring.")
    return triggers


def build_llm_analysis_enrichment(
    state: AgriState,
    final_action: str,
) -> Dict[str, Any] | None:
    if httpx is None:
        return None

    endpoint, api_key = resolve_llm_endpoint_and_key()
    if not api_key:
        return None

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    timeout_seconds = parse_float(os.getenv("OPENAI_TIMEOUT_SECONDS", "25")) or 25.0

    system_prompt = (
        f"{AGROMIND_IDENTITY}\n"
        "You are an agricultural risk analyst. "
        "Return strict JSON only with keys:\n"
        "1) bio_monitor_interpretation: object\n"
        "2) risk_triggers: array of short strings (1-5 items)\n"
        "Do not add markdown. Do not include any extra keys."
    )
    user_payload = (
        f"{compose_orchestrator_facts(state, final_action)}\n"
        "Task: generate concise bio-monitor interpretation and risk triggers."
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with managed_http_client(timeout_seconds=timeout_seconds) as client:
        response = http_request_with_fallbacks(
            client,
            "POST",
            endpoint,
            headers=headers,
            json_body={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_payload},
                ],
                "temperature": 0.0,
            },
        )
        safe_raise_for_status(response)
        payload = response.json()

    choices = payload.get("choices", []) if isinstance(payload, dict) else []
    if not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message", {})
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        return None

    parsed = parse_json_object_from_text(content)
    if not isinstance(parsed, dict):
        return None

    bio_payload = parsed.get("bio_monitor_interpretation")
    triggers_payload = parsed.get("risk_triggers")
    if not isinstance(bio_payload, dict):
        bio_payload = {}

    triggers: List[str] = []
    if isinstance(triggers_payload, list):
        for item in triggers_payload:
            if isinstance(item, str):
                value = item.strip()
                if value:
                    triggers.append(value)
    if not triggers:
        return None

    return {
        "bio_monitor_interpretation": bio_payload,
        "risk_triggers": triggers[:5],
    }


def build_llm_action_decision(
    state: AgriState,
    crop_in_bbox: bool,
) -> Dict[str, Any] | None:
    if httpx is None:
        return None

    endpoint, api_key = resolve_llm_endpoint_and_key()
    if not api_key:
        return None

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    timeout_seconds = parse_float(os.getenv("OPENAI_TIMEOUT_SECONDS", "25")) or 25.0
    min_confidence = parse_float(os.getenv("ACTION_MIN_CONFIDENCE", "0.75")) or 0.75

    system_prompt = (
        f"{AGROMIND_IDENTITY}\n"
        "You are an agricultural decision engine. "
        "Based only on provided data, decide whether there is sufficient evidence "
        "for a confident action recommendation.\n"
        "Return strict JSON only with keys:\n"
        "1) recommended_action: \"sell\" | \"hold\" | null\n"
        "2) confidence: number in [0,1]\n"
        "3) sufficient_information: boolean\n"
        "4) reason: short sentence\n"
        "Rules:\n"
        "- If data is insufficient or uncertain, set recommended_action=null.\n"
        "- If crop is not detected in bbox/date, set recommended_action=null.\n"
        "- Use only sell/hold when confidence is high."
    )
    user_payload = (
        f"{compose_orchestrator_facts(state, 'none')}\n"
        f"Crop detected in bbox/date: {crop_in_bbox}\n"
        f"Minimum confidence threshold: {min_confidence}"
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with managed_http_client(timeout_seconds=timeout_seconds) as client:
        response = http_request_with_fallbacks(
            client,
            "POST",
            endpoint,
            headers=headers,
            json_body={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_payload},
                ],
                "temperature": 0.0,
            },
        )
        safe_raise_for_status(response)
        payload = response.json()

    choices = payload.get("choices", []) if isinstance(payload, dict) else []
    if not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message", {})
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        return None

    parsed = parse_json_object_from_text(content)
    if not isinstance(parsed, dict):
        return None

    action_raw = parsed.get("recommended_action")
    action = None
    if isinstance(action_raw, str):
        candidate = action_raw.strip().lower()
        if candidate in {"sell", "hold"}:
            action = candidate

    confidence = parse_float(parsed.get("confidence"))
    sufficient = parse_bool(parsed.get("sufficient_information"), default=False)
    reason = str(parsed.get("reason") or "").strip()

    if not crop_in_bbox:
        action = None
        sufficient = False
        reason = reason or "Requested crop not detected in bbox/date."
    if confidence is None or confidence < min_confidence:
        action = None
    if not sufficient:
        action = None

    return {
        "recommended_action": action,
        "confidence": round(confidence, 2) if confidence is not None else None,
        "sufficient_information": sufficient,
        "reason": reason or "Insufficient information or confidence for recommendation.",
    }


def build_analysis_output(
    state: AgriState,
    recommended_action: str | None,
    crop_in_bbox: bool,
) -> Dict[str, Any]:
    crop_type = normalize_crop_type(state.get("crop_type", "wheat"))
    crop_health = state.get("crop_health_data", {})
    market_stats = state.get("market_price_stats", {})
    weather = state.get("weather_forecast", {})
    bio = state.get("bio_monitor", {})
    normalized_action = (
        str(recommended_action).strip().lower()
        if isinstance(recommended_action, str) and recommended_action.strip()
        else None
    )

    geospatial_context = {
        "location": state.get("location_name"),
        "country_code": state.get("country_code"),
        "bbox": state.get("bbox"),
        "requested_crop_type": crop_type,
        "selected_crop_group": crop_health.get("selected_crop_group"),
        "crop_detection_status": "detected" if crop_in_bbox else "not_detected",
    }

    yield_assessment: Dict[str, Any] | None = {
        "ndvi": crop_health.get("ndvi"),
        "yield_index": crop_health.get("yield_index"),
        "yield_index_label": crop_health.get("yield_index_label"),
        "predicted_yield_t_ha": crop_health.get("predicted_yield_t_ha"),
        "confidence": crop_health.get("confidence"),
        "status": crop_health.get("status"),
    }
    bio_interpretation: Dict[str, Any] | None = {
        "phenology_stage": bio.get("phenology_stage"),
        "bio_risk_score": bio.get("risk_score"),
        "alert_code": bio.get("alert_code"),
        "mitigation": bio.get("mitigation"),
        "stress_summary": bio.get("stress_summary"),
    }
    risk_triggers_value: List[str] | None = infer_risk_triggers(state, crop_in_bbox)

    if not crop_in_bbox:
        yield_assessment = None
        bio_interpretation = None
        risk_triggers_value = None
        recommended_action_value: str | None = None
        risk_score_value: int | None = None
    else:
        recommended_action_value = normalized_action if normalized_action in {"sell", "hold"} else None
        risk_score_value = infer_risk_score_1_to_5(state)
        try:
            llm_enriched = build_llm_analysis_enrichment(state, normalized_action or "none")
        except Exception:
            llm_enriched = None
        if isinstance(llm_enriched, dict):
            llm_bio = llm_enriched.get("bio_monitor_interpretation")
            llm_triggers = llm_enriched.get("risk_triggers")
            if isinstance(llm_bio, dict) and llm_bio:
                bio_interpretation = llm_bio
            if isinstance(llm_triggers, list) and llm_triggers:
                risk_triggers_value = [str(item) for item in llm_triggers if str(item).strip()]

    return {
        "crop_type_in_bbox": crop_in_bbox,
        "crop_type": crop_type,
        "risk_score": risk_score_value,
        "Geospatial & Crop Context：": geospatial_context,
        "Yield & Vegetation Assessment：": yield_assessment,
        "Market & Weather Risk Assessment:": {
            "market_focus_crop": state.get("market_focus_crop"),
            "latest_price": market_stats.get("latest_price"),
            "trend_direction": market_stats.get("trend_direction"),
            "period_change_pct": market_stats.get("period_change_pct"),
            "weather_risk_score": state.get("weather_risk_score"),
            "soil_moisture_pct": weather.get("soil_moisture_pct"),
            "precipitation_mm": weather.get("precipitation_mm"),
            "heat_risk": weather.get("heat_risk"),
            "flood_risk": weather.get("flood_risk"),
        },
        "recommended_action": recommended_action_value,
        "Bio-monitor Interpretation:": bio_interpretation,
        "Risk Triggers to Watch (next planning horizon):": risk_triggers_value,
    }


def build_chat_markdown_advisory(
    state: AgriState,
    recommended_action: str | None,
    action_reason: str | None,
    action_confidence: float | None,
    crop_in_bbox: bool,
) -> str:
    crop_health = state.get("crop_health_data", {})
    yield_data = state.get("yield_analysis_data", {})
    market_stats = state.get("market_price_stats", {})
    weather = state.get("weather_forecast", {})
    bio = state.get("bio_monitor", {})
    crop_report = state.get("crop_report_data", {})
    selected_apis = normalize_requested_api_nodes(state.get("requested_api_nodes"))
    selected_set = set(selected_apis)
    include_yield = "yield_analysis_agent" in selected_set
    include_market = "market_overview_agent" in selected_set
    include_report = "crop_report_agent" in selected_set
    include_weather = "climate_agent" in selected_set
    yield_selection_reason = str(yield_data.get("selection_reason") or "")
    yield_skipped = yield_selection_reason == "skipped_by_query_router"
    normalized_action = (
        str(recommended_action).strip().lower()
        if isinstance(recommended_action, str) and recommended_action.strip()
        else None
    )
    lines = [
        "# 🌾 AgroMind Response",
        "",
        "## 🧭 User Intent",
        f"- Query: {state.get('user_query', '')}",
        f"- Orchestrator context: {AGENT_PROMPTS['orchestrator'].context}",
        f"- Crop: {state.get('crop_type', 'unknown')}",
        f"- Location: {state.get('location_name', 'unknown')} ({state.get('country_code', 'n/a')})",
        f"- BBox: {state.get('bbox')}",
        f"- Selected APIs: {selected_apis}",
        "",
    ]

    if include_yield and not yield_skipped and not crop_in_bbox:
        lines.extend(
            [
                "## ⚠️ Yield & Vegetation Assessment",
                "> **Warning: Requested crop not detected in this bbox/date window.**",
                "- Yield interpretation confidence: low (crop absence in selected bbox/date).",
                "- Recommendation: adjust bbox/date or verify crop presence before making yield-based trading decisions.",
            ]
        )

    if include_yield and not yield_skipped and crop_in_bbox:
        lines.extend(
            [
                "",
                "## 🌱 Yield & Vegetation Assessment",
                f"- NDVI: {crop_health.get('ndvi')} | Yield index: {crop_health.get('yield_index')} ({crop_health.get('yield_index_label')})",
                f"- Predicted yield (t/ha): {crop_health.get('predicted_yield_t_ha')} | Confidence: {crop_health.get('confidence')}",
            ]
        )

    if include_market:
        lines.extend(
            [
                "",
                "## 💹 Market Assessment",
                f"- Market crop: {state.get('market_focus_crop', 'n/a')}",
                f"- Latest price: {market_stats.get('latest_price')}",
                f"- Trend: {market_stats.get('trend_direction')} ({market_stats.get('period_change_pct')}%)",
            ]
        )

    if include_weather:
        lines.extend(
            [
                "",
                "## ☁️ Weather Assessment",
                f"- Weather risk: {state.get('weather_risk_score')}",
                f"- Moisture: {weather.get('soil_moisture_pct')}% | Precipitation: {weather.get('precipitation_mm')} mm",
                f"- Heat risk: {weather.get('heat_risk')} | Flood risk: {weather.get('flood_risk')}",
            ]
        )

    if include_report:
        lines.extend(
            [
                "",
                "## 📊 Financial Report Context",
                f"- Report crop: {crop_report.get('crop')}",
                f"- Source: {crop_report.get('source')}",
                f"- Summary: {crop_report.get('summary')}",
            ]
        )

    if include_yield and include_weather and crop_in_bbox and not yield_skipped:
        lines.extend(
            [
                "",
                "## 🧬 Bio-monitor Interpretation",
                f"- Stage: {bio.get('phenology_stage')} | Risk: {bio.get('risk_score')}",
                f"- Alert: {bio.get('alert_code')} | Mitigation: {bio.get('mitigation')}",
                "",
                "## 🔭 Risk Triggers (Next Horizon)",
            ]
        )
        triggers = infer_risk_triggers(state, crop_in_bbox) or []
        for trigger in triggers:
            lines.append(f"- {trigger}")

    if not (include_yield or include_market or include_weather or include_report):
        lines.extend(
            [
                "## ℹ️ Response",
                "- No data API was selected from the query. Ask for yield, market, weather, or financial report details.",
            ]
        )

    lines.extend(
        [
            "",
            "## ✅ Recommended Action",
            (
                f"- Recommended Action: {normalized_action}"
                if normalized_action in {"sell", "hold"}
                else "- Recommended Action: unavailable (insufficient confidence/information)."
            ),
        ]
    )
    if action_confidence is not None:
        lines.append(f"- Recommendation confidence: {action_confidence}")
    if action_reason:
        lines.append(f"- Recommendation note: {action_reason}")
    return "\n".join(lines)


def build_llm_general_chat_reply(state: AgriState) -> str | None:
    if httpx is None:
        return None

    endpoint, api_key = resolve_llm_endpoint_and_key()
    if not api_key:
        return None

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    timeout_seconds = parse_float(os.getenv("OPENAI_TIMEOUT_SECONDS", "25")) or 25.0
    temperature = parse_float(os.getenv("OPENAI_TEMPERATURE", "0.2"))
    if temperature is None:
        temperature = 0.2
    user_query = str(state.get("user_query", "")).strip()
    query_lc = user_query.lower()
    is_greeting_or_identity = bool(
        re.search(r"^(hi|hello|hey|yo|hola)\b", query_lc)
        or re.search(r"\b(who are you|what are you|your name)\b", query_lc)
    )

    system_prompt = (
        f"{AGROMIND_IDENTITY}\n"
        "You are handling a general conversation turn with no API data required.\n"
        "Reply naturally to the user query in concise, friendly markdown.\n"
        "If the user greets you or asks your identity, start with exactly: `Hi, I'm AgroMind.`\n"
        "You are a helpful assistant specialized in agricultural insights and recommendations.\n"
        "You can provide information about crop health, weather conditions, and market trends.\n"
        "Do not produce operations-report sections, crop diagnostics, or action recommendations "
        "unless the user explicitly asks for analysis."
    )
    user_payload = f"user_query: {user_query}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with managed_http_client(timeout_seconds=timeout_seconds) as client:
        response = http_request_with_fallbacks(
            client,
            "POST",
            endpoint,
            headers=headers,
            json_body={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_payload},
                ],
                "temperature": temperature,
            },
        )
        safe_raise_for_status(response)
        payload = response.json()

    choices = payload.get("choices", []) if isinstance(payload, dict) else []
    if not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message", {})
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        reply = content.strip()
        if is_greeting_or_identity and "agromind" not in reply.lower():
            reply = f"Hi, I'm AgroMind.\n\n{reply}"
        return reply
    return None


def build_llm_advisory(
    state: AgriState,
    recommended_action: str | None,
    action_reason: str | None,
    action_confidence: float | None,
    crop_in_bbox: bool,
) -> str | None:
    if httpx is None:
        return None

    endpoint, api_key = resolve_llm_endpoint_and_key()
    if not api_key:
        return None

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    timeout_seconds = parse_float(os.getenv("OPENAI_TIMEOUT_SECONDS", "25")) or 25.0
    temperature = parse_float(os.getenv("OPENAI_TEMPERATURE", "0.2"))
    if temperature is None:
        temperature = 0.2

    system_prompt = (
        f"{AGROMIND_IDENTITY}\n"
        f"Role: {AGENT_PROMPTS['orchestrator'].role}\n"
        f"Context: {AGENT_PROMPTS['orchestrator'].context}\n"
        f"Instruction: {AGENT_PROMPTS['orchestrator'].prompt}\n"
        "Generate a polished, visual-friendly markdown response with meaningful emojis. "
        "Keep facts strictly faithful to provided inputs and do not invent data.\n"
        "Use clear headers and concise bullets.\n"
        "Only use API sections that were selected by routing; if an API was skipped, omit that section.\n"
        "If crop is not detected in bbox/date, prominently include:\n"
        "> **Warning: Requested crop not detected in this bbox/date window.**\n"
        "and avoid framing it as biological stress.\n"
        "Use Crop report markdown as primary financial context when available, and reconcile it with market-overview stats.\n"
        "If and only if a high-confidence action signal is provided, include one line exactly as: "
        "`Recommended Action: <action>` where <action> is sell or hold.\n"
        "If action signal is absent, state that recommendation is unavailable due to uncertainty/insufficient evidence.\n"
        "Do not output chain-of-thought."
    )

    normalized_action = (
        str(recommended_action).strip().lower()
        if isinstance(recommended_action, str) and recommended_action.strip()
        else ""
    )
    user_payload = (
        f"{compose_orchestrator_facts(state, normalized_action or 'none')}\n"
        f"Crop detected in bbox/date: {crop_in_bbox}\n"
        f"Action signal: {normalized_action or 'none'}\n"
        f"Action confidence: {action_confidence}\n"
        f"Action reason: {action_reason or ''}"
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with managed_http_client(timeout_seconds=timeout_seconds) as client:
        response = http_request_with_fallbacks(
            client,
            "POST",
            endpoint,
            headers=headers,
            json_body={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_payload},
                ],
                "temperature": temperature,
            },
        )
        safe_raise_for_status(response)
        payload = response.json()

    choices = payload.get("choices", []) if isinstance(payload, dict) else []
    if not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message", {})
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    return None


def geocode_node(state: AgriState) -> Dict[str, Any]:
    if not state.get("need_geo", True):
        parsed_bbox = normalize_bbox(state.get("bbox"))
        if parsed_bbox is None:
            return {
                "geocode_status": "failed",
                "geocode_error": "bbox_missing_or_invalid",
                "needs_clarification": True,
                "clarification_message": "need_geo is false but bbox is missing or invalid.",
                "geocode_debug": "failed_bbox_from_query_invalid_or_missing",
            }

        min_lon, min_lat, max_lon, max_lat = parsed_bbox
        center_lat = (min_lat + max_lat) / 2
        center_lon = (min_lon + max_lon) / 2
        return {
            "country_code": "FR",
            "location_name": f"bbox center lat {center_lat:.4f}, lon {center_lon:.4f}",
            "bbox": parsed_bbox,
            "geocode_debug": "bbox_from_user_query",
            "geocode_status": "resolved",
        }

    field_name = (state.get("field_name") or "").strip() or "Unknown Farm"
    candidates = geocode_candidates(field_name)
    last_error = ""
    attempted: List[str] = []

    for candidate in candidates:
        attempted.append(candidate)
        preset_result = known_bbox_for_location(candidate)
        if preset_result:
            preset_result["location_name"] = candidate
            preset_result["geocode_status"] = "resolved"
            return preset_result
        try:
            live_result = API_ADAPTERS.geocode_with_nominatim(candidate)
            if live_result:
                live_result["location_name"] = candidate
                live_result["geocode_debug"] = f"live_nominatim:{candidate}"
                live_result["geocode_status"] = "resolved"
                return live_result
        except Exception as exc:
            last_error = exception_to_error_code("geocoding", exc)
            continue

    if last_error:
        error_reason = last_error
    else:
        error_reason = "geocoding_not_found_or_non_fr"

    return {
        "geocode_status": "failed",
        "geocode_error": error_reason,
        "needs_clarification": True,
        "clarification_message": (
            f"Could not geocode location from candidates {attempted} "
            f"({error_reason}). Provide a more specific French commune, department, or postal code."
        ),
        "geocode_debug": f"failed_geocode_no_fabricated_bbox:{attempted}",
    }


def select_crop_from_yield_response(
    crops: Dict[str, Any],
    crop_profiles: Dict[str, Any],
    crop_type: str,
) -> tuple[str, Dict[str, Any], Dict[str, Any], str]:
    preferred = map_crop_type_to_yield_group(crop_type)
    crop_payload = crops.get(preferred)
    profile_payload = crop_profiles.get(preferred)
    has_crop_payload = isinstance(crop_payload, dict) and bool(crop_payload)
    has_profile_payload = isinstance(profile_payload, dict) and bool(profile_payload)

    if has_crop_payload and has_profile_payload:
        return preferred, crop_payload, profile_payload, "query_crop_and_profile_match"
    if has_crop_payload:
        return preferred, crop_payload, {}, "query_crop_match"
    if has_profile_payload:
        return preferred, {}, profile_payload, "query_profile_only_match"

    # Do not cross-fallback to a different crop group when the requested crop
    # is absent in the backend payload for this bbox/date.
    return preferred, {}, {}, "requested_crop_not_detected"


def build_no_crop_detected_health(
    selected_group: str,
    date_range: str,
) -> CropHealthData:
    latest_scene_date = date_range.split("/")[-1] if "/" in date_range else date_range
    return {
        "ndvi": 0.6,
        "leaf_area_index": 1.92,
        "status": "No crop detected",
        "selected_crop_group": selected_group,
        "selected_crop_label": selected_group.replace("_", " ").title(),
        "yield_index": 1.0,
        "yield_index_label": "Requested crop not detected in bbox/date",
        "predicted_yield_t_ha": 0.0,
        "target_year": datetime.now().year,
        "confidence": 0.1,
        "anomaly_vs_5yr_pct": 0.0,
        "estimated_yield_delta_pct": 0.0,
        "satellite_history_signal": "stable",
        "latest_scene_date": latest_scene_date,
        "cloud_cover_pct": 0.0,
        "cropland_coverage_pct": 0.0,
        "segmented_area_ha": 0.0,
        "source": f"{API_CONFIG.yield_analysis} (requested crop not detected)",
    }


def month_from_date_range(date_range: str) -> int | None:
    latest = date_range.split("/")[-1].strip() if "/" in date_range else date_range.strip()
    if not latest:
        return None
    try:
        return datetime.fromisoformat(latest).month
    except ValueError:
        return None


def build_profile_context(
    crop_profile: Dict[str, Any],
    date_range: str,
) -> Dict[str, Any]:
    if not isinstance(crop_profile, dict):
        return {}

    context: Dict[str, Any] = {}
    peak_months = crop_profile.get("peak_months")
    optimal_ndvi_range = crop_profile.get("optimal_ndvi_range")
    stress_threshold = parse_float(crop_profile.get("stress_threshold"))
    baseline_by_month = crop_profile.get("baseline_by_month")
    month = month_from_date_range(date_range)
    month_baseline = None

    if isinstance(baseline_by_month, dict) and month is not None:
        month_baseline = parse_float(
            baseline_by_month.get(str(month), baseline_by_month.get(month))
        )

    if isinstance(peak_months, list):
        context["peak_months"] = peak_months
    if isinstance(optimal_ndvi_range, list):
        context["optimal_ndvi_range"] = optimal_ndvi_range
    if stress_threshold is not None:
        context["stress_threshold"] = stress_threshold
    if month_baseline is not None:
        context["ndvi_baseline_used"] = month_baseline
    if isinstance(baseline_by_month, dict):
        context["baseline_by_month"] = baseline_by_month
    return context


def build_crop_health_from_yield_payload(
    bbox: List[float],
    selected_group: str,
    selected_crop_payload: Dict[str, Any],
    selected_crop_profile: Dict[str, Any],
    date_range: str,
) -> CropHealthData:
    profile_context = build_profile_context(selected_crop_profile, date_range)
    merged_payload = dict(profile_context)
    merged_payload.update(selected_crop_payload)

    ndvi = round(parse_float(merged_payload.get("ndvi_mean")) or 0.0, 3)
    yield_index = round(parse_float(merged_payload.get("yield_index")) or 0.0, 3)
    yield_index_label = str(merged_payload.get("yield_index_label") or "Unknown")
    area_pct = round(parse_float(merged_payload.get("area_pct")) or 0.0, 1)
    prediction = merged_payload.get("yield_prediction")
    predicted_yield = None
    anomaly_pct = None
    target_year = None
    confidence = 0.0
    if isinstance(prediction, dict):
        predicted_yield = parse_float(prediction.get("predicted_yield_t_ha"))
        anomaly_pct = parse_float(prediction.get("anomaly_vs_5yr_pct"))
        target_year_raw = prediction.get("target_year")
        target_year = int(target_year_raw) if isinstance(target_year_raw, int) else None
        confidence = round(parse_float(prediction.get("confidence")) or 0.0, 2)
    estimated_delta = anomaly_pct if anomaly_pct is not None else round((yield_index - 1.0) * 100.0, 1)
    status = "Healthy" if yield_index >= 1.0 else ("Watch" if yield_index >= 0.85 else "Stress")
    history_signal = "stable" if estimated_delta >= -5.0 else "declining"
    area_ha = round(bbox_area_hectares(bbox) * max(area_pct, 0.0) / 100.0, 2)
    latest_scene_date = date_range.split("/")[-1] if "/" in date_range else date_range
    return {
        "ndvi": ndvi,
        "leaf_area_index": round(max(0.4, ndvi * 3.2), 2),
        "status": status,
        "selected_crop_group": selected_group,
        "selected_crop_label": str(merged_payload.get("label") or selected_group),
        "yield_index": yield_index,
        "yield_index_label": yield_index_label,
        "predicted_yield_t_ha": round(predicted_yield, 2) if predicted_yield is not None else 0.0,
        "target_year": target_year or datetime.now().year,
        "confidence": confidence,
        "anomaly_vs_5yr_pct": round(estimated_delta, 1),
        "estimated_yield_delta_pct": round(estimated_delta, 1),
        "satellite_history_signal": history_signal,
        "latest_scene_date": latest_scene_date,
        "cloud_cover_pct": 0.0,
        "cropland_coverage_pct": area_pct,
        "segmented_area_ha": area_ha,
        "source": (
            f"{API_CONFIG.yield_analysis} (crop+profile)"
            if selected_crop_profile
            else API_CONFIG.yield_analysis
        ),
    }


def yield_analysis_node(state: AgriState) -> Dict[str, Any]:
    crop_type = normalize_crop_type(state.get("crop_type", "wheat"))
    if not should_run_api_node(state, "yield_analysis_agent"):
        selected_group = map_crop_type_to_yield_group(crop_type)
        return {
            "crop_health_data": {
                "ndvi": 0.0,
                "leaf_area_index": 0.0,
                "status": "Not requested",
                "selected_crop_group": selected_group,
                "selected_crop_label": selected_group.replace("_", " ").title(),
                "yield_index": 0.0,
                "yield_index_label": "Not requested",
                "predicted_yield_t_ha": 0.0,
                "target_year": datetime.now().year,
                "confidence": 0.0,
                "anomaly_vs_5yr_pct": 0.0,
                "estimated_yield_delta_pct": 0.0,
                "satellite_history_signal": "unknown",
                "latest_scene_date": "",
                "cloud_cover_pct": 0.0,
                "cropland_coverage_pct": 0.0,
                "segmented_area_ha": 0.0,
                "source": f"{API_CONFIG.yield_analysis} (skipped)",
            },
            "yield_analysis_data": {
                "selection_reason": "skipped_by_query_router",
                "summary": "Yield analysis skipped because it was not requested in chat mode.",
            },
            "yield_analysis_debug": "skipped_by_query_router",
            "yield_analysis_error": "",
        }

    bbox = state["bbox"]
    yield_error = ""
    live_payload = None
    try:
        live_payload = API_ADAPTERS.search_yield_analysis(bbox=bbox)
    except Exception as exc:
        yield_error = exception_to_error_code("yield_analysis_fetch", exc)

    if isinstance(live_payload, dict):
        crops_payload = live_payload.get("crops")
        crop_profiles_payload = live_payload.get("crop_profiles")
        crops_map = crops_payload if isinstance(crops_payload, dict) else {}
        crop_profiles_map = crop_profiles_payload if isinstance(crop_profiles_payload, dict) else {}
        if crops_map or crop_profiles_map:
            selected_group, selected_crop_payload, selected_crop_profile, selection_reason = select_crop_from_yield_response(
                crops_map,
                crop_profiles_map,
                crop_type,
            )
            date_range = str(live_payload.get("date_range") or "")
            if selection_reason in {"requested_crop_not_detected", "query_profile_only_match"}:
                crop_health = build_no_crop_detected_health(
                    selected_group=selected_group,
                    date_range=date_range,
                )
                profile_context = build_profile_context(selected_crop_profile, date_range)
                if selection_reason == "query_profile_only_match":
                    message = (
                        f"{selected_group} not detected in this bbox/date window; "
                        "crop profile exists but no crop metrics were returned."
                    )
                else:
                    message = f"{selected_group} not detected in this bbox/date window."
                return {
                    "crop_health_data": crop_health,
                    "yield_analysis_data": {
                        "endpoint": live_payload.get("endpoint"),
                        "bbox": live_payload.get("bbox"),
                        "date_range": date_range,
                        "total_classified_pixels": live_payload.get("total_classified_pixels"),
                        "selected_crop_group": selected_group,
                        "selected_crop": {},
                        "selected_crop_profile": selected_crop_profile if selected_crop_profile else {},
                        "selected_crop_profile_context": profile_context,
                        "selection_reason": selection_reason,
                        "summary": message,
                    },
                    "yield_analysis_debug": f"live_backend_yield_analysis:{selection_reason}",
                    "yield_analysis_error": yield_error,
                }
            crop_health = build_crop_health_from_yield_payload(
                bbox=bbox,
                selected_group=selected_group,
                selected_crop_payload=selected_crop_payload,
                selected_crop_profile=selected_crop_profile,
                date_range=date_range,
            )
            selected_profile_context = build_profile_context(selected_crop_profile, date_range)
            return {
                "crop_health_data": crop_health,
                "yield_analysis_data": {
                    "endpoint": live_payload.get("endpoint"),
                    "bbox": live_payload.get("bbox"),
                    "date_range": date_range,
                    "total_classified_pixels": live_payload.get("total_classified_pixels"),
                    "selected_crop_group": selected_group,
                    "selected_crop": selected_crop_payload,
                    "selected_crop_profile": selected_crop_profile if selected_crop_profile else {},
                    "selected_crop_profile_context": selected_profile_context,
                    "selection_reason": selection_reason,
                    "summary": live_payload.get("summary", ""),
                },
                "yield_analysis_debug": f"live_backend_yield_analysis:{selection_reason}",
                "yield_analysis_error": yield_error,
            }

    spread = abs(bbox[2] - bbox[0]) + abs(bbox[3] - bbox[1])
    ndvi = round(clamp(0.72 - (spread * 0.15), 0.2, 0.88), 2)
    yield_index = round(clamp(0.98 - (spread * 0.12), 0.55, 1.25), 2)
    area_pct = round(clamp(40 + (yield_index * 20), 5, 95), 1)
    selected_group = map_crop_type_to_yield_group(crop_type)
    estimated_delta = round((yield_index - 1.0) * 100.0, 1)
    crop_health_fallback: CropHealthData = {
        "ndvi": ndvi,
        "leaf_area_index": round(max(0.4, ndvi * 3.2), 2),
        "status": "Healthy" if yield_index >= 1.0 else ("Watch" if yield_index >= 0.85 else "Stress"),
        "selected_crop_group": selected_group,
        "selected_crop_label": selected_group.replace("_", " ").title(),
        "yield_index": yield_index,
        "yield_index_label": "Fallback estimate",
        "predicted_yield_t_ha": round(max(2.0, 5.5 * yield_index), 2),
        "target_year": datetime.now().year,
        "confidence": 0.35,
        "anomaly_vs_5yr_pct": estimated_delta,
        "estimated_yield_delta_pct": estimated_delta,
        "satellite_history_signal": "stable" if estimated_delta >= -5 else "declining",
        "latest_scene_date": datetime.now().date().isoformat(),
        "cloud_cover_pct": 0.0,
        "cropland_coverage_pct": area_pct,
        "segmented_area_ha": round(bbox_area_hectares(bbox) * area_pct / 100.0, 2),
        "source": f"{API_CONFIG.yield_analysis} (fallback simulation)",
    }
    return {
        "crop_health_data": crop_health_fallback,
        "yield_analysis_data": {
            "endpoint": "/agent/yield-analysis",
            "bbox": bbox,
            "date_range": "",
            "selected_crop_group": selected_group,
            "selection_reason": "fallback_from_query_crop",
            "summary": "Yield analysis backend unavailable; generated deterministic fallback from bbox size.",
        },
        "yield_analysis_debug": "fallback_simulated_yield_analysis",
        "yield_analysis_error": yield_error or "yield_analysis_fetch:not_available",
    }


def select_crop_from_market_prices(prices: Dict[str, Any], crop_type: str) -> tuple[str, str]:
    preferred = map_crop_type_to_market_crop(crop_type)
    if preferred in prices:
        return preferred, "query_crop_match"
    for candidate in ["wheat", "maize", "grape"]:
        if candidate in prices:
            return candidate, f"fallback_to_{candidate}"
    return "wheat", "default_wheat"


def market_overview_node(state: AgriState) -> Dict[str, Any]:
    crop_type = normalize_crop_type(state.get("crop_type", "wheat"))
    if not should_run_api_node(state, "market_overview_agent"):
        return {
            "market_focus_crop": map_crop_type_to_market_crop(crop_type),
            "market_price_stats": {},
            "market_overview_data": {
                "selected_crop": map_crop_type_to_market_crop(crop_type),
                "selection_reason": "skipped_by_query_router",
                "summary": "Market overview skipped because it was not requested in chat mode.",
            },
            "market_overview_debug": "skipped_by_query_router",
            "market_overview_error": "",
        }

    market_error = ""
    live_payload = None
    try:
        live_payload = API_ADAPTERS.search_market_overview()
    except Exception as exc:
        market_error = exception_to_error_code("market_overview_fetch", exc)

    if isinstance(live_payload, dict):
        prices = live_payload.get("prices")
        weather = live_payload.get("weather")
        weather_stats = weather.get("stats", {}) if isinstance(weather, dict) else {}
        if isinstance(prices, dict) and prices:
            market_crop, selection_reason = select_crop_from_market_prices(prices, crop_type)
            selected_price = prices.get(market_crop, {}) if isinstance(prices.get(market_crop), dict) else {}
            stats = selected_price.get("stats", {}) if isinstance(selected_price.get("stats"), dict) else {}
            return {
                "market_focus_crop": market_crop,
                "market_price_stats": stats,
                "market_overview_data": {
                    "endpoint": live_payload.get("endpoint"),
                    "period": live_payload.get("period"),
                    "selected_crop": market_crop,
                    "selection_reason": selection_reason,
                    "price_stats": stats,
                    "weather_stats": weather_stats,
                    "summary": live_payload.get("summary", ""),
                },
                "market_overview_debug": f"live_backend_market_overview:{selection_reason}",
                "market_overview_error": market_error,
            }

    fallback_crop = map_crop_type_to_market_crop(crop_type)
    fallback_stats = {
        "latest_price": 170.0,
        "earliest_price": 180.0,
        "period_change_pct": -5.6,
        "high": 210.0,
        "low": 150.0,
        "trend_direction": "stable",
    }
    return {
        "market_focus_crop": fallback_crop,
        "market_price_stats": fallback_stats,
        "market_overview_data": {
            "endpoint": "/agent/market-overview",
            "selected_crop": fallback_crop,
            "selection_reason": "fallback_from_query_crop",
            "price_stats": fallback_stats,
            "weather_stats": {},
            "summary": "Market overview backend unavailable; generated deterministic fallback signals.",
        },
        "market_overview_debug": "fallback_simulated_market_overview",
        "market_overview_error": market_error or "market_overview_fetch:not_available",
    }


def crop_report_node(state: AgriState) -> Dict[str, Any]:
    crop_type = normalize_crop_type(state.get("crop_type", "wheat"))
    if not should_run_api_node(state, "crop_report_agent"):
        return {
            "crop_report_data": {
                "crop": None,
                "source": API_CONFIG.crop_report,
                "summary": "Crop report skipped because it was not requested in chat mode.",
                "report_markdown": "",
                "report_char_count": 0,
                "truncated": False,
            },
            "crop_report_debug": "skipped_by_query_router",
            "crop_report_error": "",
        }

    report_crop = map_crop_type_to_report_crop(crop_type)
    if report_crop is None:
        return {
            "crop_report_data": {
                "crop": None,
                "source": API_CONFIG.crop_report,
                "summary": f"No dedicated crop report available for '{crop_type}'.",
                "report_markdown": "",
                "report_char_count": 0,
                "truncated": False,
            },
            "crop_report_debug": "skipped_unsupported_crop_for_report",
            "crop_report_error": "",
        }

    crop_report_error = ""
    report_payload = None
    try:
        report_payload = API_ADAPTERS.search_crop_report(report_crop)
    except Exception as exc:
        crop_report_error = exception_to_error_code("crop_report_fetch", exc)

    if isinstance(report_payload, dict):
        report_text = str(report_payload.get("report") or "").strip()
        if report_text:
            max_chars = parse_env_int("CROP_REPORT_MAX_CHARS", 12000)
            truncated = len(report_text) > max_chars
            report_markdown = report_text[:max_chars] if truncated else report_text
            summary = f"Loaded {report_crop} markdown financial report."
            return {
                "crop_report_data": {
                    "endpoint": report_payload.get("endpoint"),
                    "crop": report_payload.get("crop", report_crop),
                    "format": report_payload.get("format", "markdown"),
                    "source": API_CONFIG.crop_report,
                    "summary": summary,
                    "report_markdown": report_markdown,
                    "report_char_count": len(report_text),
                    "truncated": truncated,
                },
                "crop_report_debug": "live_backend_crop_report",
                "crop_report_error": crop_report_error,
            }

    # Local fallback when backend endpoint is unavailable.
    report_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "backend",
            "data",
            "reports",
            f"{report_crop}_analysis.md",
        )
    )
    if os.path.isfile(report_path):
        try:
            with open(report_path, "r", encoding="utf-8") as handle:
                report_text = handle.read().strip()
        except Exception as exc:
            crop_report_error = (
                crop_report_error
                or exception_to_error_code("crop_report_local_read", exc)
            )
            report_text = ""
        if report_text:
            max_chars = parse_env_int("CROP_REPORT_MAX_CHARS", 12000)
            truncated = len(report_text) > max_chars
            report_markdown = report_text[:max_chars] if truncated else report_text
            return {
                "crop_report_data": {
                    "endpoint": "/agent/crop-report (local fallback)",
                    "crop": report_crop,
                    "format": "markdown",
                    "source": f"{API_CONFIG.crop_report} (local fallback)",
                    "summary": f"Loaded local {report_crop} markdown financial report.",
                    "report_markdown": report_markdown,
                    "report_char_count": len(report_text),
                    "truncated": truncated,
                },
                "crop_report_debug": "local_fallback_crop_report",
                "crop_report_error": crop_report_error,
            }

    return {
        "crop_report_data": {
            "crop": report_crop,
            "source": API_CONFIG.crop_report,
            "summary": f"Crop report unavailable for {report_crop}.",
            "report_markdown": "",
            "report_char_count": 0,
            "truncated": False,
        },
        "crop_report_debug": "crop_report_not_available",
        "crop_report_error": crop_report_error or "crop_report_fetch:not_available",
    }


def bbox_center(bbox: List[float]) -> tuple[float, float]:
    center_lon = round((bbox[0] + bbox[2]) / 2, 4)
    center_lat = round((bbox[1] + bbox[3]) / 2, 4)
    return center_lat, center_lon


def climate_node(state: AgriState) -> Dict[str, Any]:
    if not should_run_api_node(state, "climate_agent"):
        return {
            "weather_risk_score": 0.0,
            "weather_forecast": {
                "days": 0,
                "source": f"{API_CONFIG.weather} (skipped)",
                "soil_moisture_pct": 0.0,
                "precipitation_mm": 0.0,
                "flood_risk": 0.0,
                "heat_risk": 0.0,
                "extreme_event": None,
            },
            "weather_debug": "skipped_by_query_router",
            "weather_error": "",
        }

    center_lat, center_lon = bbox_center(state["bbox"])

    weather_error = ""
    try:
        live_forecast = API_ADAPTERS.fetch_meteo_france_forecast(center_lat, center_lon)
    except Exception as exc:
        weather_error = exception_to_error_code("climate_forecast_fetch", exc)
        live_forecast = None

    if live_forecast:
        weather_risk = live_forecast["weather_risk_score"]
        normalized_forecast = dict(live_forecast)
        normalized_forecast.pop("weather_risk_score", None)
        return {
            "weather_risk_score": weather_risk,
            "weather_forecast": normalized_forecast,
            "weather_debug": "live_open_meteo_meteofrance_seamless",
            "weather_error": weather_error,
        }

    crop = state.get("crop_type", "wheat").lower()
    lat_bias = (state["bbox"][1] - 41.0) * 0.2
    base_moisture = 18.5 if crop in {"wheat", "maize"} else 23.0
    soil_moisture = round(max(7.0, base_moisture - lat_bias), 1)
    precipitation = round(max(2.0, 26.0 - (soil_moisture * 0.7)), 1)
    flood_risk = round(clamp(0.18 + (precipitation * 0.01)), 2)
    heat_risk = round(clamp(0.22 + ((20.0 - soil_moisture) * 0.03)), 2)
    weather_risk = round(clamp((heat_risk * 0.55) + (flood_risk * 0.45)), 2)
    return {
        "weather_risk_score": weather_risk,
        "weather_forecast": {
            "days": 14,
            "source": API_CONFIG.weather,
            "soil_moisture_pct": soil_moisture,
            "precipitation_mm": precipitation,
            "flood_risk": flood_risk,
            "heat_risk": heat_risk,
            "extreme_event": "100-year Flood" if flood_risk >= 0.85 else None,
        },
        "weather_debug": "fallback_simulated_weather",
        "weather_error": weather_error or "climate_forecast_fetch:not_available",
    }


def determine_growth_stage(ndvi: float) -> str:
    if ndvi >= 0.82:
        return "Flowering"
    if ndvi >= 0.67:
        return "Grain Filling"
    if ndvi >= 0.52:
        return "Vegetative"
    return "Senescence"


def bio_monitor_node(state: AgriState) -> Dict[str, Any]:
    crop_health = state.get("crop_health_data", {})
    weather = state.get("weather_forecast", {})
    if not crop_health or not weather:
        report: BioMonitorReport = {
            "risk_score": 0.25,
            "phenology_stage": "Unknown",
            "mitigation": "Insufficient inputs for bio-monitor assessment.",
            "alert_code": "NORMAL",
            "stress_summary": "Bio-monitor skipped due missing yield/weather inputs.",
            "critical_growth_stage": False,
        }
        return {"bio_monitor": report, "phenology_stage": "Unknown"}

    ndvi = parse_float(crop_health.get("ndvi")) or 0.0
    weather_risk_score = parse_float(state.get("weather_risk_score")) or 0.0
    moisture = parse_float(weather.get("soil_moisture_pct")) or 0.0
    market_stats = state.get("market_price_stats", {})
    stage = determine_growth_stage(ndvi)
    history_signal = crop_health.get("satellite_history_signal", "stable")
    estimated_delta = parse_float(crop_health.get("estimated_yield_delta_pct")) or 0.0
    market_trend = str(market_stats.get("trend_direction") or "stable")
    critical_stage = stage in {"Flowering", "Grain Filling"}
    risk_score = clamp((1 - ndvi) * 0.55 + weather_risk_score * 0.45)
    alert_code = "NORMAL"
    mitigation = "Continue monitoring"

    if estimated_delta <= -15:
        risk_score = clamp(risk_score + 0.15)
        mitigation = "Yield anomaly is strongly negative; prioritize in-field stress diagnostics"
    if critical_stage and moisture < 20:
        risk_score = clamp(risk_score + 0.35)
        alert_code = "CRITICAL_DROUGHT_RISK"
        mitigation = "Increase irrigation and protect the current growth window"
    elif stage == "Senescence" and history_signal == "stable":
        risk_score = clamp(risk_score - 0.2)
        mitigation = "Dry-down appears seasonal; prepare harvest operations"
    elif history_signal == "declining":
        risk_score = clamp(risk_score + 0.15)
        mitigation = "Inspect for disease pressure and nutrient stress"
    elif market_trend == "falling" and estimated_delta < 0:
        mitigation = "Combine crop protection with hedging because yield and market both weaken"

    report: BioMonitorReport = {
        "risk_score": round(risk_score, 2),
        "phenology_stage": stage,
        "mitigation": mitigation,
        "alert_code": alert_code,
        "stress_summary": f"{stage} stage, NDVI {ndvi}, moisture {moisture}%",
        "critical_growth_stage": critical_stage,
    }
    return {"bio_monitor": report, "phenology_stage": stage}


def climate_priority_node(state: AgriState) -> Dict[str, Any]:
    weather = dict(state["weather_forecast"])
    boosted_risk = clamp(state["weather_risk_score"] + 0.12)
    weather["heat_risk"] = round(clamp(weather["heat_risk"] + 0.1), 2)
    return {
        "weather_risk_score": round(boosted_risk, 2),
        "weather_forecast": weather,
    }


def emergency_dispatcher_node(state: AgriState) -> Dict[str, Any]:
    bio = state["bio_monitor"]
    message = (
        f"EMERGENCY: {bio['alert_code']} in {state['location_name']}. "
        f"Mitigation: {bio['mitigation']}."
    )
    return {
        "is_emergency": True,
        "emergency_dispatch": {
            "channel": "sms",
            "message": message,
            "dispatched": True,
        },
    }


def orchestrator_node(state: AgriState) -> Dict[str, Any]:
    mode = normalize_run_mode(state.get("run_mode", "chat"))
    selected_api_nodes = normalize_requested_api_nodes(state.get("requested_api_nodes"))
    crop_in_bbox = crop_type_detected_in_bbox(state)

    if mode == "chat" and not selected_api_nodes:
        llm_reply = None
        llm_error = ""
        try:
            llm_reply = build_llm_general_chat_reply(state)
        except Exception as exc:
            llm_error = exception_to_error_code("orchestrator_general_chat_llm", exc)

        if llm_reply:
            return {
                "final_advisory": llm_reply,
                "orchestrator_debug": "llm_general_chat_no_api",
                "orchestrator_error": llm_error,
            }

        return {
            "final_advisory": (
                "Hi, I'm AgroMind.\n\n"
                "I can help with crop, yield, weather, and market analysis when you ask for it. "
                "For now, this looks like a general chat question, so no data APIs were called."
            ),
            "orchestrator_debug": "fallback_general_chat_no_api",
            "orchestrator_error": (
                llm_error
                or (
                    "orchestrator_general_chat_llm:invalid_response"
                    if os.getenv("OPENAI_API_KEY")
                    else "orchestrator_general_chat_llm:not_configured"
                )
            ),
        }

    recommended_action: str | None = None
    action_confidence: float | None = None
    action_reason = ""
    action_error = ""

    if not crop_in_bbox:
        action_reason = "Requested crop is not detected in the selected bbox/date."
    else:
        action_decision = None
        try:
            action_decision = build_llm_action_decision(state, crop_in_bbox)
        except Exception as exc:
            action_error = exception_to_error_code("action_decision_llm", exc)
        if isinstance(action_decision, dict):
            candidate = str(action_decision.get("recommended_action") or "").strip().lower()
            if candidate in {"sell", "hold"}:
                recommended_action = candidate
            action_confidence = parse_float(action_decision.get("confidence"))
            action_reason = str(action_decision.get("reason") or "").strip()
        if not action_reason and not recommended_action:
            action_reason = "Insufficient information or confidence for a recommendation."

    if mode == "analysis":
        analysis_payload = build_analysis_output(state, recommended_action, crop_in_bbox)
        return {
            "final_advisory": json.dumps(analysis_payload, ensure_ascii=False, indent=2),
            "orchestrator_debug": "structured_analysis_json_with_llm_action_decision",
            "orchestrator_error": action_error,
        }

    orchestrator_error = ""
    llm_advisory = None
    try:
        llm_advisory = build_llm_advisory(
            state,
            recommended_action,
            action_reason,
            action_confidence,
            crop_in_bbox,
        )
    except Exception as exc:
        orchestrator_error = exception_to_error_code("orchestrator_llm", exc)

    combined_error = ";".join([part for part in [action_error, orchestrator_error] if part])

    if llm_advisory:
        return {
            "final_advisory": llm_advisory,
            "orchestrator_debug": "llm_openai_chat_completions",
            "orchestrator_error": combined_error,
        }

    return {
        "final_advisory": build_chat_markdown_advisory(
            state=state,
            recommended_action=recommended_action,
            action_reason=action_reason,
            action_confidence=action_confidence,
            crop_in_bbox=crop_in_bbox,
        ),
        "orchestrator_debug": "fallback_chat_markdown_orchestrator",
        "orchestrator_error": (
            combined_error
            or (
                "orchestrator_llm:invalid_response"
                if os.getenv("OPENAI_API_KEY")
                else "orchestrator_llm:not_configured"
            )
        ),
    }


def route_after_bio(state: AgriState) -> Literal["climate_priority", "emergency_dispatcher", "orchestrator"]:
    bio = state.get("bio_monitor", {})
    if (parse_float(bio.get("risk_score")) or 0.0) > 0.8:
        return "emergency_dispatcher"
    if bool(bio.get("critical_growth_stage")):
        return "climate_priority"
    return "orchestrator"


def route_after_validation(state: AgriState) -> Literal["geocoding_agent", "dispatch_downstream", "clarification_node"]:
    if state.get("query_validation_status") == "validated":
        mode = normalize_run_mode(state.get("run_mode", "chat"))
        if mode == "chat" and not selected_api_nodes_need_geocoding(state):
            return "dispatch_downstream"
        return "geocoding_agent"
    return "clarification_node"


def route_after_geocode(state: AgriState) -> Literal["dispatch_downstream", "clarification_node"]:
    if state.get("geocode_status") == "resolved":
        return "dispatch_downstream"
    mode = normalize_run_mode(state.get("run_mode", "chat"))
    if mode == "chat" and not selected_api_nodes_need_geocoding(state):
        return "dispatch_downstream"
    return "clarification_node"


def geocode_dispatch_node(_: AgriState) -> Dict[str, Any]:
    return {}


def log_node_output(node_name: str, output: Dict[str, Any]) -> None:
    try:
        serialized = json.dumps(output, default=str, ensure_ascii=True)
    except TypeError:
        serialized = str(output)
    LOGGER.info("node=%s output=%s", node_name, serialized)


def with_node_logging(
    node_name: str,
    node_fn: Callable[[AgriState], Dict[str, Any]],
) -> Callable[[AgriState], Dict[str, Any]]:
    def wrapped(state: AgriState) -> Dict[str, Any]:
        output = node_fn(state)
        log_node_output(node_name, output)
        return output

    return wrapped


def build_graph():
    if StateGraph is None:
        raise RuntimeError(
            "LangGraph is not installed. Install dependencies with "
            "`python3 -m pip install -r requirements.txt`."
        )

    graph = StateGraph(AgriState)
    graph.add_node("query_analysis_agent", with_node_logging("query_analysis_agent", query_analysis_node))
    graph.add_node("query_validation", with_node_logging("query_validation", validation_node))
    graph.add_node("clarification_node", with_node_logging("clarification_node", clarification_node))
    graph.add_node("geocoding_agent", with_node_logging("geocoding_agent", geocode_node))
    graph.add_node("geocode_dispatch", with_node_logging("geocode_dispatch", geocode_dispatch_node))
    graph.add_node("yield_analysis_agent", with_node_logging("yield_analysis_agent", yield_analysis_node))
    graph.add_node("market_overview_agent", with_node_logging("market_overview_agent", market_overview_node))
    graph.add_node("crop_report_agent", with_node_logging("crop_report_agent", crop_report_node))
    graph.add_node("climate_agent", with_node_logging("climate_agent", climate_node))
    graph.add_node("bio_monitor", with_node_logging("bio_monitor", bio_monitor_node))
    graph.add_node("climate_priority", with_node_logging("climate_priority", climate_priority_node))
    graph.add_node("emergency_dispatcher", with_node_logging("emergency_dispatcher", emergency_dispatcher_node))
    graph.add_node("orchestrator", with_node_logging("orchestrator", orchestrator_node))

    graph.add_edge(START, "query_analysis_agent")
    graph.add_edge("query_analysis_agent", "query_validation")
    graph.add_conditional_edges(
        "query_validation",
        route_after_validation,
        {
            "geocoding_agent": "geocoding_agent",
            "dispatch_downstream": "geocode_dispatch",
            "clarification_node": "clarification_node",
        },
    )
    graph.add_conditional_edges(
        "geocoding_agent",
        route_after_geocode,
        {
            "dispatch_downstream": "geocode_dispatch",
            "clarification_node": "clarification_node",
        },
    )
    graph.add_edge("geocode_dispatch", "yield_analysis_agent")
    graph.add_edge("geocode_dispatch", "market_overview_agent")
    graph.add_edge("geocode_dispatch", "crop_report_agent")
    graph.add_edge("geocode_dispatch", "climate_agent")
    graph.add_edge("yield_analysis_agent", "bio_monitor")
    graph.add_edge("market_overview_agent", "bio_monitor")
    graph.add_edge("crop_report_agent", "bio_monitor")
    graph.add_edge("climate_agent", "bio_monitor")
    graph.add_conditional_edges(
        "bio_monitor",
        route_after_bio,
        {
            "climate_priority": "climate_priority",
            "emergency_dispatcher": "emergency_dispatcher",
            "orchestrator": "orchestrator",
        },
    )
    graph.add_edge("climate_priority", "orchestrator")
    graph.add_edge("emergency_dispatcher", "orchestrator")
    graph.add_edge("orchestrator", END)
    graph.add_edge("clarification_node", END)
    return graph.compile()


def run_agri_mind(
    user_query: str,
    run_mode: str = "chat",
) -> AgriState:
    app = build_graph()
    mode = normalize_run_mode(run_mode)
    initial_state: AgriState = {
        "user_query": user_query,
        "run_mode": mode,
        "is_emergency": False,
    }
    return app.invoke(initial_state)


def run_agri_pulse_nexus(
    user_query: str,
    run_mode: str = "chat",
) -> AgriState:
    return run_agri_mind(user_query=user_query, run_mode=run_mode)


def print_architecture_summary(mode) -> None:
    print("AgroMind LangGraph Skeleton")
    print("==================================")
    print("HTTP Client: httpx")
    print(f"Geocoding: {API_CONFIG.geocoding}")
    print(f"Yield Analysis: {API_CONFIG.yield_analysis}")
    print(f"Market Overview: {API_CONFIG.market_overview}")
    print(f"Weather: {API_CONFIG.weather}")
    print(f"User-Agent: {API_ADAPTERS.user_agent}")
    print(f"Run modes: {mode}")
    print(f"Use LLM: {os.getenv('OPENAI_API_KEY') is not None}")
    print(f"LLM Model: {os.getenv('OPENAI_MODEL')}")
    print("\nGraph")
    print("-----")
    print("START -> query_analysis_agent -> query_validation")
    print("query_validation -> geocoding_agent OR geocode_dispatch (chat mode without geo-required APIs) OR clarification_node -> END")
    print("geocoding_agent -> geocode_dispatch (if resolved) OR clarification_node -> END")
    print("geocode_dispatch -> [yield_analysis_agent || market_overview_agent || crop_report_agent || climate_agent] (chat mode may skip API fetches by query routing)")
    print("bio_monitor -> emergency_dispatcher (if bio risk > 0.8) -> orchestrator")
    print("bio_monitor -> climate_priority (if critical stage) -> orchestrator")
    print("bio_monitor -> orchestrator (otherwise) -> END")


def main() -> None:
    mode = "chat"
    print_architecture_summary(mode)
    try:
        state = run_agri_mind(
            user_query="Hello, what is your capacity? what can you do?",
            run_mode=mode,
        )
    except RuntimeError as exc:
        print(f"\nRuntime note: {exc}")
        return

    print("\nRun Output")
    print("==========")
    print(state["final_advisory"])
    if state.get("is_emergency"):
        print("\nEmergency Dispatch")
        print("==================")
        print(state["emergency_dispatch"]["message"])


if __name__ == "__main__":
    main()
