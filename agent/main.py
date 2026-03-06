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
    central_lat_lon: List[float]
    crop_type: str
    analysis_report: str


class AgriState(TypedDict, total=False):
    user_query: str
    field_name: str | None
    need_geo: bool
    central_lat_lon: List[float]
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
    user_agent: str = "AgriMaster/0.1"

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

LOGGER = logging.getLogger("agrimaster")
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
        context="You extract farm location mode (field-name or coordinate) and crop from user text.",
        prompt=(
            "Extract field_name, need_geo, central_lat_lon, crop_type, and a concise analysis report from the user query."
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
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
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


def parse_env_int(var_name: str, default: int) -> int:
    raw = os.getenv(var_name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


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
        "rhone valley france": [4.50, 45.50, 4.80, 45.80],
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
    central = extract_lat_lon_from_text(query)
    if central:
        return {
            "field_name": None,
            "need_geo": False,
            "central_lat_lon": central,
            "crop_type": crop,
            "analysis_report": (
                f"Parsed coordinates lat {central[0]}, lon {central[1]} from user query "
                f"for crop {crop}. Geocoding skipped."
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

    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    endpoint = os.getenv("OPENAI_API_URL", "https://openrouter.ai/api/v1/chat/completions")
    model = os.getenv("OPENAI_MODEL", "qwen/qwen3.5-flash-02-23")
    timeout_seconds = parse_float(os.getenv("OPENAI_TIMEOUT_SECONDS", "25")) or 25.0
    referer = os.getenv("OPENROUTER_HTTP_REFERER")
    title = os.getenv("OPENROUTER_X_TITLE", "AgriMaster")

    system_prompt = (
        f"Role: {AGENT_PROMPTS['query_analysis_agent'].role}\n"
        f"Context: {AGENT_PROMPTS['query_analysis_agent'].context}\n"
        f"Instruction: {AGENT_PROMPTS['query_analysis_agent'].prompt}\n"
        "Return valid JSON only with keys: field_name, need_geo, central_lat_lon, crop_type, analysis_report. "
        "If query has latitude/longitude, set need_geo=false, field_name=null, and central_lat_lon=[lat,lon]. "
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
    if referer:
        headers["HTTP-Referer"] = referer
    if title:
        headers["X-Title"] = title

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
    central_raw = parsed.get("central_lat_lon")
    central_lat_lon: List[float] | None = None
    if isinstance(central_raw, list) and len(central_raw) >= 2:
        lat = parse_float(central_raw[0])
        lon = parse_float(central_raw[1])
        if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
            central_lat_lon = [round(lat, 6), round(lon, 6)]
    analysis_report = str(parsed.get("analysis_report") or "").strip()

    if not crop_type:
        crop_type = fallback_crop
    if not analysis_report:
        analysis_report = "Parsed query intent."

    if not need_geo:
        if not central_lat_lon:
            central_lat_lon = extract_lat_lon_from_text(user_query)
        if not central_lat_lon:
            return None
        return {
            "field_name": None,
            "need_geo": False,
            "central_lat_lon": central_lat_lon,
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

    llm_result = None
    query_error = ""
    try:
        llm_result = build_llm_query_analysis(user_query, fallback_crop)
    except Exception as exc:
        query_error = exception_to_error_code("query_analysis_llm", exc)

    if llm_result:
        result: Dict[str, Any] = {
            "crop_type": llm_result["crop_type"],
            "query_analysis_report": llm_result["analysis_report"],
            "query_analysis_debug": "llm_query_analysis",
        }
        if llm_result.get("need_geo", True):
            result["need_geo"] = True
            result["field_name"] = llm_result.get("field_name")
        else:
            result["need_geo"] = False
            result["field_name"] = None
            result["central_lat_lon"] = llm_result["central_lat_lon"]
        return result

    fallback_result = fallback_query_analysis(user_query, fallback_crop)
    result: Dict[str, Any] = {
        "crop_type": fallback_result["crop_type"],
        "query_analysis_report": fallback_result["analysis_report"],
        "query_analysis_debug": "fallback_query_analysis",
    }
    if query_error:
        result["query_analysis_error"] = query_error
    elif (os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")):
        result["query_analysis_error"] = "query_analysis_llm:invalid_response"
    else:
        result["query_analysis_error"] = "query_analysis_llm:not_configured"
    if fallback_result.get("need_geo", True):
        result["need_geo"] = True
        result["field_name"] = fallback_result.get("field_name")
    else:
        result["need_geo"] = False
        result["field_name"] = None
        result["central_lat_lon"] = fallback_result["central_lat_lon"]
    return result


def validation_node(state: AgriState) -> Dict[str, Any]:
    allowed_crops = {"wheat", "maize", "grape", "barley", "soy", "coffee", "sugar", "cotton"}
    crop_type = normalize_crop_type(state.get("crop_type", "wheat"))
    need_geo = bool(state.get("need_geo", True))
    field_name = (state.get("field_name") or "").strip()
    central = state.get("central_lat_lon") or []

    issues: List[str] = []
    if crop_type not in allowed_crops:
        issues.append(f"unsupported_crop_type:{crop_type}")
    if need_geo:
        if len(field_name) < 3:
            issues.append("field_name_missing_or_too_short")
    else:
        if not isinstance(central, list) or len(central) < 2:
            issues.append("central_lat_lon_missing")
        else:
            lat = parse_float(central[0])
            lon = parse_float(central[1])
            if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                issues.append("central_lat_lon_invalid")

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

    return {
        "crop_type": crop_type,
        "need_geo": need_geo,
        "query_validation_status": "validated",
        "needs_clarification": False,
    }


def clarification_node(state: AgriState) -> Dict[str, Any]:
    clarification = state.get(
        "clarification_message",
        "Need more detail to continue.",
    )
    report = state.get("query_analysis_report", "No query-analysis report was produced.")
    user_query = state.get("user_query", "")
    field_name = state.get("field_name", "Unknown")
    need_geo = state.get("need_geo", True)
    central = state.get("central_lat_lon", [])
    crop_type = state.get("crop_type", "Unknown")
    return {
        "final_advisory": "\n".join(
            [
                "Analysis paused - clarification required.",
                f"User query: {user_query}",
                f"Parsed field_name: {field_name}",
                f"need_geo: {need_geo}",
                f"Parsed central_lat_lon: {central}",
                f"Parsed crop: {crop_type}",
                f"Query analysis report: {report}",
                f"Reason: {clarification}",
                "Please provide either a field/location name or explicit latitude/longitude, plus crop type.",
            ]
        )
    }


def compose_orchestrator_facts(state: AgriState, final_action: str) -> str:
    forecast = state["weather_forecast"]
    bio = state["bio_monitor"]
    crop_health = state["crop_health_data"]
    market_crop = state.get("market_focus_crop", "wheat")
    market_stats = state.get("market_price_stats", {})
    yield_data = state.get("yield_analysis_data", {})
    market_data = state.get("market_overview_data", {})
    crop_report_data = state.get("crop_report_data", {})
    crop_report_md = str(crop_report_data.get("report_markdown") or "").strip()
    return "\n".join(
        [
            f"User query: {state.get('user_query', '')}",
            f"Query analysis report: {state.get('query_analysis_report', 'n/a')}",
            f"Query analysis debug: {state.get('query_analysis_debug', 'n/a')}",
            f"Field name: {state.get('field_name')}",
            f"need_geo: {state.get('need_geo', True)}",
            f"central_lat_lon: {state.get('central_lat_lon')}",
            f"Location: {state['location_name']} ({state['country_code']})",
            f"BBox: {state['bbox']}",
            f"Geocode debug: {state['geocode_debug']}",
            f"Crop: {state['crop_type']}",
            f"Yield selected crop group: {crop_health.get('selected_crop_group', 'n/a')}",
            f"Stage: {state['phenology_stage']}",
            f"Yield source: {crop_health['source']} NDVI {crop_health['ndvi']} yield_index {crop_health.get('yield_index')}",
            (
                f"Yield debug: {state.get('yield_analysis_debug', 'n/a')} | coverage "
                f"{crop_health.get('cropland_coverage_pct', 0)}% | area "
                f"{crop_health.get('segmented_area_ha', 0)} ha | confidence "
                f"{crop_health.get('confidence', 0)}"
            ),
            f"Weather: {forecast['source']} risk {state['weather_risk_score']} moisture {forecast['soil_moisture_pct']}%",
            f"Weather debug: {state['weather_debug']}",
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
            f"Mitigation: {bio['mitigation']}",
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


def build_llm_advisory(
    state: AgriState,
    final_action: str,
    override_reason: str | None,
) -> str | None:
    if httpx is None:
        return None

    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    endpoint = os.getenv("OPENAI_API_URL", "https://openrouter.ai/api/v1/chat/completions")
    model = os.getenv("OPENAI_MODEL", "qwen/qwen3.5-flash-02-23")
    timeout_seconds = parse_float(os.getenv("OPENAI_TIMEOUT_SECONDS", "25")) or 25.0
    temperature = parse_float(os.getenv("OPENAI_TEMPERATURE", "0.2"))
    if temperature is None:
        temperature = 0.2
    referer = os.getenv("OPENROUTER_HTTP_REFERER")
    title = os.getenv("OPENROUTER_X_TITLE", "AgriMaster")

    system_prompt = (
        f"Role: {AGENT_PROMPTS['orchestrator'].role}\n"
        f"Context: {AGENT_PROMPTS['orchestrator'].context}\n"
        f"Instruction: {AGENT_PROMPTS['orchestrator'].prompt}\n"
        "Write a comprehensive operations report for agriculture stakeholders. "
        "Keep facts strictly faithful to provided inputs and do not invent data.\n"
        "Output must be polished, readable markdown with clear section headers, concise bullets, "
        "and compact tables where useful.\n"
        "Use the provided `Crop report markdown` as the primary source for crop-specific "
        "financial intelligence when it is available (wheat/corn/grape). "
        "If crop report markdown is unavailable or empty, explicitly say so and rely on "
        "market overview + weather + yield inputs only.\n"
        "Do not copy long verbatim passages from the markdown report; synthesize key signals "
        "into concise, decision-oriented statements.\n"
        "Required output format (markdown):\n"
        "1) Executive Summary (3-5 sentences)\n"
        "2) Parsed User Intent\n"
        "3) Geospatial & Crop Context\n"
        "4) Yield & Vegetation Assessment\n"
        "5) Market & Weather Risk Assessment\n"
        "6) Bio-monitor Interpretation\n"
        "7) Recommended Action Plan\n"
        "8) Risk Triggers to Watch (next planning horizon)\n"
        "9) Confidence & Data Quality Notes\n"
        "If yield analysis indicates the requested crop is not detected in the bbox/date "
        "(for example `selection_reason=requested_crop_not_detected`, "
        "`yield_index_label` contains `not detected`, or status is `No crop detected`), "
        "then in section 4 add a prominent warning line exactly like:\n"
        "> **Warning: Requested crop not detected in this bbox/date window.**\n"
        "In that case, do not frame the result as biological stress, and explicitly mark "
        "yield interpretation confidence as low due to crop absence.\n"
        "In section 5, if crop report markdown is present, include at least two financial "
        "signals from it (for example futures momentum, supply regime, FX, oil/input costs, "
        "or demand structure) and reconcile them with market-overview stats.\n"
        "In section 7, include exactly one line: `Recommended Action: <action>` where "
        "<action> matches the provided action signal. Do not output chain-of-thought."
    )

    user_payload = compose_orchestrator_facts(state, final_action)
    if override_reason:
        user_payload = f"{user_payload}\nOverride reason: {override_reason}"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if referer:
        headers["HTTP-Referer"] = referer
    if title:
        headers["X-Title"] = title

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
        central = state.get("central_lat_lon") or []
        if not isinstance(central, list) or len(central) < 2:
            return {
                "geocode_status": "failed",
                "geocode_error": "central_lat_lon_missing",
                "needs_clarification": True,
                "clarification_message": "need_geo is false but central_lat_lon is missing.",
                "geocode_debug": "failed_bbox_from_center_missing_coords",
            }
        lat = parse_float(central[0])
        lon = parse_float(central[1])
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return {
                "geocode_status": "failed",
                "geocode_error": "central_lat_lon_invalid",
                "needs_clarification": True,
                "clarification_message": "need_geo is false but central_lat_lon is invalid.",
                "geocode_debug": "failed_bbox_from_center_invalid_coords",
            }

        bbox = bbox_from_center_lat_lon(lat, lon)
        return {
            "country_code": "FR",
            "location_name": f"lat {lat:.4f}, lon {lon:.4f}",
            "bbox": bbox,
            "geocode_debug": "bbox_from_central_lat_lon_fixed_size",
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
    crop_type: str,
) -> tuple[str, Dict[str, Any], str]:
    preferred = map_crop_type_to_yield_group(crop_type)
    if preferred in crops and isinstance(crops[preferred], dict):
        return preferred, crops[preferred], "query_crop_match"

    # Do not cross-fallback to a different crop group when the requested crop
    # is absent in the backend payload for this bbox/date.
    return preferred, {}, "requested_crop_not_detected"


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


def build_crop_health_from_yield_payload(
    bbox: List[float],
    selected_group: str,
    selected_crop_payload: Dict[str, Any],
    date_range: str,
) -> CropHealthData:
    ndvi = round(parse_float(selected_crop_payload.get("ndvi_mean")) or 0.0, 3)
    yield_index = round(parse_float(selected_crop_payload.get("yield_index")) or 0.0, 3)
    yield_index_label = str(selected_crop_payload.get("yield_index_label") or "Unknown")
    area_pct = round(parse_float(selected_crop_payload.get("area_pct")) or 0.0, 1)
    prediction = selected_crop_payload.get("yield_prediction")
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
        "selected_crop_label": str(selected_crop_payload.get("label") or selected_group),
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
        "source": API_CONFIG.yield_analysis,
    }


def yield_analysis_node(state: AgriState) -> Dict[str, Any]:
    bbox = state["bbox"]
    crop_type = normalize_crop_type(state.get("crop_type", "wheat"))
    yield_error = ""
    live_payload = None
    try:
        live_payload = API_ADAPTERS.search_yield_analysis(bbox=bbox)
    except Exception as exc:
        yield_error = exception_to_error_code("yield_analysis_fetch", exc)

    if isinstance(live_payload, dict):
        crops_payload = live_payload.get("crops")
        if isinstance(crops_payload, dict) and crops_payload:
            selected_group, selected_crop_payload, selection_reason = select_crop_from_yield_response(
                crops_payload,
                crop_type,
            )
            date_range = str(live_payload.get("date_range") or "")
            if selection_reason == "requested_crop_not_detected":
                crop_health = build_no_crop_detected_health(
                    selected_group=selected_group,
                    date_range=date_range,
                )
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
                date_range=date_range,
            )
            return {
                "crop_health_data": crop_health,
                "yield_analysis_data": {
                    "endpoint": live_payload.get("endpoint"),
                    "bbox": live_payload.get("bbox"),
                    "date_range": date_range,
                    "total_classified_pixels": live_payload.get("total_classified_pixels"),
                    "selected_crop_group": selected_group,
                    "selected_crop": selected_crop_payload,
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
    crop_health = state["crop_health_data"]
    weather = state["weather_forecast"]
    market_stats = state.get("market_price_stats", {})
    stage = determine_growth_stage(crop_health["ndvi"])
    moisture = weather["soil_moisture_pct"]
    history_signal = crop_health.get("satellite_history_signal", "stable")
    estimated_delta = parse_float(crop_health.get("estimated_yield_delta_pct")) or 0.0
    market_trend = str(market_stats.get("trend_direction") or "stable")
    critical_stage = stage in {"Flowering", "Grain Filling"}
    risk_score = clamp((1 - crop_health["ndvi"]) * 0.55 + state["weather_risk_score"] * 0.45)
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
        "stress_summary": f"{stage} stage, NDVI {crop_health['ndvi']}, moisture {moisture}%",
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
    bio = state["bio_monitor"]
    forecast = state["weather_forecast"]
    market_stats = state.get("market_price_stats", {})
    stage = state.get("phenology_stage", "")
    moisture = parse_float(forecast.get("soil_moisture_pct"))
    price_change = parse_float(market_stats.get("period_change_pct"))
    trend_direction = str(market_stats.get("trend_direction") or "stable")
    final_action = "Hold"
    override_reason = None

    if forecast.get("extreme_event"):
        final_action = "Sell"
        override_reason = "Extreme weather risk requires immediate risk reduction."
    elif trend_direction == "falling" and price_change is not None and price_change <= -20:
        final_action = "Sell"
        override_reason = "Market trend is sharply negative; reduce downside exposure."
    elif stage in {"Flowering", "Grain Filling"} and moisture is not None and moisture >= 80:
        final_action = "Sell"
        override_reason = "Very high moisture in a critical stage increases disease pressure risk."
    elif bio["risk_score"] >= 0.85:
        final_action = "Sell"
        override_reason = "Severe biological stress requires immediate risk reduction."

    orchestrator_error = ""
    llm_advisory = None
    try:
        llm_advisory = build_llm_advisory(state, final_action, override_reason)
    except Exception as exc:
        orchestrator_error = exception_to_error_code("orchestrator_llm", exc)

    if llm_advisory:
        return {
            "final_advisory": llm_advisory,
            "orchestrator_debug": "llm_openai_chat_completions",
            "orchestrator_error": orchestrator_error,
        }

    return {
        "final_advisory": build_rule_based_advisory(state, final_action, override_reason),
        "orchestrator_debug": "fallback_rule_based_orchestrator",
        "orchestrator_error": (
            orchestrator_error
            or (
                "orchestrator_llm:invalid_response"
                if (os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY"))
                else "orchestrator_llm:not_configured"
            )
        ),
    }


def route_after_bio(state: AgriState) -> Literal["climate_priority", "emergency_dispatcher", "orchestrator"]:
    if state["bio_monitor"]["risk_score"] > 0.8:
        return "emergency_dispatcher"
    if state["bio_monitor"]["critical_growth_stage"]:
        return "climate_priority"
    return "orchestrator"


def route_after_validation(state: AgriState) -> Literal["geocoding_agent", "clarification_node"]:
    if state.get("query_validation_status") == "validated":
        return "geocoding_agent"
    return "clarification_node"


def route_after_geocode(state: AgriState) -> Literal["dispatch_downstream", "clarification_node"]:
    if state.get("geocode_status") == "resolved":
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


def run_agri_pulse_nexus(
    user_query: str,
    run_mode: str = "interactive",
) -> AgriState:
    app = build_graph()
    initial_state: AgriState = {
        "user_query": user_query,
        "run_mode": run_mode,
        "is_emergency": False,
    }
    return app.invoke(initial_state)


def print_architecture_summary() -> None:
    print("AgriMaster LangGraph Skeleton")
    print("==================================")
    print("HTTP Client: httpx")
    print(f"Geocoding: {API_CONFIG.geocoding}")
    print(f"Yield Analysis: {API_CONFIG.yield_analysis}")
    print(f"Market Overview: {API_CONFIG.market_overview}")
    print(f"Weather: {API_CONFIG.weather}")
    print(f"User-Agent: {API_ADAPTERS.user_agent}")
    print("\nGraph")
    print("-----")
    print("START -> query_analysis_agent -> query_validation")
    print("query_validation -> geocoding_agent (validated) OR clarification_node -> END")
    print("geocoding_agent -> [yield_analysis_agent || market_overview_agent || crop_report_agent || climate_agent] (if resolved) OR clarification_node -> END")
    print("bio_monitor -> emergency_dispatcher (if bio risk > 0.8) -> orchestrator")
    print("bio_monitor -> climate_priority (if critical stage) -> orchestrator")
    print("bio_monitor -> orchestrator (otherwise) -> END")


def main() -> None:
    print_architecture_summary()
    try:
        state = run_agri_pulse_nexus(
            user_query="Assess wheat risk and selling strategy at lat: 48.8566, lon: 2.3522.",
            run_mode="cron",
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
