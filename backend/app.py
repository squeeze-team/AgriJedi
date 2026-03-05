"""
AgriIntel — FastAPI backend
============================
Endpoints:
  GET /                        → health check
  GET /map/overlay             → Sentinel-2 + CLMS overlay PNG
  GET /weather/france          → monthly weather aggregates
  GET /predict/yield           → yield anomaly prediction
  GET /predict/price           → 3-month price direction forecast
  GET /crops                   → available crop configs
  GET /prices/history          → monthly price time-series
  GET /yield/history           → annual yield time-series
  GET /ndvi/stats              → NDVI summary statistics

Agent-oriented (POST JSON body, single-call):
  POST /agent/yield-analysis   → per-crop NDVI + yield forecast for a bbox
  POST /agent/market-overview  → 3-crop price history + weather trends
"""

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

from config import CROP_CONFIG, DEFAULT_CROP, FRANCE_BBOX

from services.s2_pc import get_ndvi_stats, get_s2_overlay_png, get_satellite_visualization
from services.clms_wms import get_crop_type_overlay
from services.crop_ndvi_analysis import analyze_crop_ndvi, _CROP_NDVI_PROFILES
from services.weather_power import get_weather_monthly
from services.faostat import get_yield_history, compute_yield_features
from services.prices_worldbank import get_price_history, compute_price_features

from features.build_features import build_feature_vector
from features.models import predict_yield, predict_price

app = FastAPI(
    title="AgriIntel Demo",
    version="0.1.0",
    description="France wheat yield & price prediction framework",
)

# Allow the frontend to call the API from any origin (hackathon-friendly)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Health check ────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok", "service": "AgriIntel Demo"}


# ─── Available crops ─────────────────────────────────────────────
@app.get("/crops")
def list_crops():
    """Return the list of supported crops and their metadata."""
    return {
        name: {
            "description": cfg["description"],
            "growing_season_months": cfg["growing_season_months"],
        }
        for name, cfg in CROP_CONFIG.items()
    }


# ─── Map overlay ─────────────────────────────────────────────────
@app.get("/map/overlay")
async def map_overlay(
    bbox: str = Query(
        default=",".join(map(str, FRANCE_BBOX)),
        description="west,south,east,north in EPSG:4326",
    ),
    date: str = Query(
        default="2024-06-01/2024-09-01",
        description="Date or date range for Sentinel-2 search",
    ),
    width: int = Query(default=512, ge=64, le=2048),
    height: int = Query(default=512, ge=64, le=2048),
):
    """
    Return a PNG image combining Sentinel-2 RGB with
    the CLMS Crop Types overlay.
    """
    try:
        west, south, east, north = [float(v) for v in bbox.split(",")]
    except Exception:
        raise HTTPException(400, "bbox must be west,south,east,north")

    png_bytes = get_s2_overlay_png(
        bbox=[west, south, east, north],
        date_range=date,
        width=width,
        height=height,
    )
    return StreamingResponse(png_bytes, media_type="image/png")


# ─── Satellite visualisation panel ────────────────────────────────
@app.get("/satellite/view")
async def satellite_view(
    bbox: str = Query(
        default="4.67,44.71,4.97,45.01",
        description="west,south,east,north in EPSG:4326",
    ),
    date: str = Query(
        default="2025-06-01/2025-09-01",
        description="Date range for Sentinel-2 search",
    ),
    layer: str = Query(
        default="rgb",
        description="Visualisation type: rgb, false_color, ndvi, overlay",
    ),
    width: int = Query(default=600, ge=64, le=2048),
    height: int = Query(default=600, ge=64, le=2048),
):
    """
    Return a single satellite visualisation PNG for the given bbox and layer type.

    Layers:
      - **rgb** — Sentinel-2 true-colour
      - **false_color** — NIR-R-G composite
      - **ndvi** — NDVI heatmap (RdYlGn)
      - **overlay** — RGB + CLMS Crop Types
    """
    valid_layers = ("rgb", "false_color", "ndvi", "overlay")
    if layer not in valid_layers:
        raise HTTPException(400, f"Unknown layer '{layer}'. Use: {valid_layers}")

    try:
        west, south, east, north = [float(v) for v in bbox.split(",")]
    except Exception:
        raise HTTPException(400, "bbox must be west,south,east,north")

    buf, meta = get_satellite_visualization(
        bbox=[west, south, east, north],
        date_range=date,
        vis_type=layer,
        width=width,
        height=height,
    )
    return StreamingResponse(
        buf,
        media_type="image/png",
        headers={
            "X-Item-Id": str(meta.get("item_id") or ""),
            "X-Item-Date": str(meta.get("date") or ""),
            "X-Cloud-Cover": str(meta.get("cloud_cover") or ""),
        },
    )


# ─── Weather time-series ─────────────────────────────────────────
@app.get("/weather/france")
async def weather_france(
    start: str = Query(default="20230101", description="yyyyMMdd"),
    end: str = Query(default="20241231", description="yyyyMMdd"),
):
    """Return monthly-aggregated weather data for France (3×3 grid mean)."""
    data = get_weather_monthly(start_date=start, end_date=end)
    return JSONResponse(content=data)


# ─── Yield prediction ────────────────────────────────────────────
@app.get("/predict/yield")
async def yield_prediction(
    crop: str = Query(default=DEFAULT_CROP),
    country: str = Query(default="France"),
):
    """Predict national yield anomaly for the given crop."""
    if crop not in CROP_CONFIG:
        raise HTTPException(400, f"Unknown crop '{crop}'. Available: {list(CROP_CONFIG)}")

    features = build_feature_vector(crop=crop, country=country)
    result = predict_yield(features, crop=crop)
    return JSONResponse(content=result)


# ─── Price prediction ────────────────────────────────────────────
@app.get("/predict/price")
async def price_prediction(
    crop: str = Query(default=DEFAULT_CROP),
):
    """Forecast 3-month price direction for the given crop."""
    if crop not in CROP_CONFIG:
        raise HTTPException(400, f"Unknown crop '{crop}'. Available: {list(CROP_CONFIG)}")

    features = build_feature_vector(crop=crop)
    result = predict_price(features, crop=crop)
    return JSONResponse(content=result)


# ─── Price history ───────────────────────────────────────────────
@app.get("/prices/history")
async def price_history(
    crop: str = Query(default=DEFAULT_CROP),
):
    """Return monthly commodity price time-series for the given crop."""
    if crop not in CROP_CONFIG:
        raise HTTPException(400, f"Unknown crop '{crop}'. Available: {list(CROP_CONFIG)}")

    df = get_price_history(crop)
    if df.empty:
        return JSONResponse(content={"dates": [], "prices": []})

    return JSONResponse(content={
        "crop": crop,
        "dates": df["date"].dt.strftime("%Y-%m").tolist(),
        "prices": df["price"].round(2).tolist(),
        "unit": "USD/mt",
    })


# ─── Yield history ──────────────────────────────────────────────
@app.get("/yield/history")
async def yield_history(
    crop: str = Query(default=DEFAULT_CROP),
):
    """Return annual yield time-series for the given crop in France."""
    if crop not in CROP_CONFIG:
        raise HTTPException(400, f"Unknown crop '{crop}'. Available: {list(CROP_CONFIG)}")

    df = get_yield_history(crop)
    if df.empty:
        return JSONResponse(content={"years": [], "yields": []})

    return JSONResponse(content={
        "crop": crop,
        "country": "France",
        "years": df["year"].tolist(),
        "yields": df["yield_ton_ha"].round(3).tolist(),
        "unit": "ton/ha",
    })


# ─── NDVI statistics ────────────────────────────────────────────
@app.get("/ndvi/stats")
async def ndvi_stats(
    crop: str = Query(default=DEFAULT_CROP),
    date: str = Query(
        default="2024-04-01/2024-07-01",
        description="Date range for NDVI calculation",
    ),
):
    """Return NDVI summary statistics (with fallback to bundled data)."""
    if crop not in CROP_CONFIG:
        raise HTTPException(400, f"Unknown crop '{crop}'. Available: {list(CROP_CONFIG)}")

    stats = get_ndvi_stats(date_range=date, crop=crop)
    return JSONResponse(content={"crop": crop, **stats})


# ─── Crop-level NDVI analysis ────────────────────────────────────
@app.get("/analysis/crop-ndvi")
async def crop_ndvi_analysis(
    bbox: str = Query(
        default="4.67,44.71,4.97,45.01",
        description="west,south,east,north in EPSG:4326",
    ),
    date: str = Query(
        default="2025-06-01/2025-09-01",
        description="Date range for Sentinel-2 search",
    ),
    resolution: int = Query(
        default=400, ge=100, le=1000,
        description="Grid resolution (pixels, width = height)",
    ),
):
    """
    Classify crop types via CLMS WMS colour-reverse-lookup, then
    compute per-crop NDVI statistics and a relative yield proxy.
    """
    try:
        west, south, east, north = [float(v) for v in bbox.split(",")]
    except Exception:
        raise HTTPException(400, "bbox must be west,south,east,north")

    result = analyze_crop_ndvi(
        bbox=[west, south, east, north],
        date_range=date,
        resolution=resolution,
    )
    return JSONResponse(content=result)


# ═══════════════════════════════════════════════════════════════════
# Agent-oriented endpoints — POST JSON, one-call-per-task
# ═══════════════════════════════════════════════════════════════════


class YieldAnalysisRequest(BaseModel):
    bbox: list[float] = Field(
        default=[4.67, 44.71, 4.97, 45.01],
        description="Bounding box [west, south, east, north] in EPSG:4326",
        min_length=4,
        max_length=4,
    )
    date: str = Field(
        default="2025-06-01/2025-09-01",
        description="Sentinel-2 date range (YYYY-MM-DD/YYYY-MM-DD)",
    )


class MarketOverviewRequest(BaseModel):
    start: str = Field(
        default="20230101",
        description="Weather period start date (yyyyMMdd)",
    )
    end: str = Field(
        default="20251231",
        description="Weather period end date (yyyyMMdd)",
    )


@app.post("/agent/yield-analysis")
async def agent_yield_analysis(req: YieldAnalysisRequest):
    """
    **Agent endpoint** — Per-crop yield analysis for a geographic region.

    Returns a single JSON containing:
      - Per-crop NDVI statistics (mean, median, std, IQR, pixel count)
      - NDVI-based yield index (ratio vs 5-year baseline)
      - Agreste-backed yield forecast in t/ha with confidence & explanation
      - Summary text suitable for LLM consumption

    Crops covered: wheat, maize, grape (+ other_cereal, grassland, other).
    """
    bbox_list = req.bbox
    date = req.date
    if len(bbox_list) != 4:
        raise HTTPException(400, "bbox must be [west, south, east, north]")
    west, south, east, north = bbox_list
    analysis = analyze_crop_ndvi(bbox=bbox_list, date_range=date)

    # Build a concise text summary for LLM agents
    summary_lines = [
        f"Region: bbox [{west}, {south}, {east}, {north}]",
        f"Analysis date range: {date}",
        f"Total classified pixels: {analysis.get('total_classified_pixels', 'N/A')}",
        "",
    ]
    crops = analysis.get("crops", {})
    for group, c in crops.items():
        yi = c.get("yield_index")
        yi_str = f"{yi:.2f}" if yi is not None else "N/A"
        baseline = c.get("ndvi_baseline_used", "?")
        peak = c.get("peak_months", [])
        peak_str = ",".join(str(m) for m in peak) if peak else "?"
        line = (
            f"- {group} ({c.get('label','')}) : area {c.get('area_pct',0)}%, "
            f"NDVI mean {c.get('ndvi_mean','?')} (baseline {baseline}, peak months {peak_str}), "
            f"yield index {yi_str} [{c.get('yield_index_label','')}]"
        )
        yp = c.get("yield_prediction")
        if yp and yp.get("predicted_yield_t_ha") is not None:
            conf = yp.get('confidence', 0)
            sign = '+' if yp['anomaly_vs_5yr_pct'] >= 0 else ''
            line += (
                f" → forecast {yp['predicted_yield_t_ha']} t/ha "
                f"({yp['target_year']}, {sign}{yp['anomaly_vs_5yr_pct']}% vs 5yr avg, "
                f"confidence {conf:.0%})"
            )
            if yp.get("confidence_note"):
                line += f" ⚠ {yp['confidence_note']}"
        obs = c.get("observation_note")
        if obs:
            line += f"\n    Note: {obs}"
        summary_lines.append(line)

    return JSONResponse(content={
        "endpoint": "/agent/yield-analysis",
        "bbox": bbox_list,
        "date_range": date,
        "total_classified_pixels": analysis.get("total_classified_pixels"),
        "crops": crops,
        "crop_profiles": {
            group: {
                "peak_months": prof["peak_months"],
                "peak_ndvi_range": list(prof["peak_ndvi"]),
                "summer_ndvi_range": list(prof["summer_ndvi"]),
                "optimal_ndvi_range": list(prof["optimal_range"]),
                "stress_threshold": prof["stress_threshold"],
                "baseline_by_month": prof["baseline_by_month"],
            }
            for group, prof in _CROP_NDVI_PROFILES.items()
        },
        "summary": "\n".join(summary_lines),
    })


@app.post("/agent/market-overview")
async def agent_market_overview(req: MarketOverviewRequest):
    """
    **Agent endpoint** — Multi-crop price history + weather trends in one call.

    Returns a single JSON containing:
      - Monthly price series for wheat, maize, and grape (USD/mt)
      - Monthly weather for France (precipitation, temperature, peak temperature)
      - Computed price statistics (latest price, 12-month change %, trend direction)
      - Weather statistics (avg temp, total precip, heat-stress months)
      - Summary text suitable for LLM consumption
    """
    start = req.start
    end = req.end
    # ── Collect price data for all 3 crops ──
    crop_names = ["wheat", "maize", "grape"]
    price_data: dict[str, dict] = {}
    for crop in crop_names:
        df = get_price_history(crop)
        if df.empty:
            price_data[crop] = {"dates": [], "prices": [], "unit": "USD/mt", "stats": {}}
            continue
        dates = df["date"].dt.strftime("%Y-%m").tolist()
        prices = df["price"].round(2).tolist()
        latest = prices[-1] if prices else None
        oldest = prices[0] if prices else None
        change_pct = round((latest - oldest) / oldest * 100, 1) if oldest and latest else None
        # 6-month moving direction
        if len(prices) >= 6:
            recent_avg = sum(prices[-3:]) / 3
            older_avg = sum(prices[-6:-3]) / 3
            trend = "rising" if recent_avg > older_avg * 1.02 else ("falling" if recent_avg < older_avg * 0.98 else "stable")
        else:
            trend = "insufficient data"

        price_data[crop] = {
            "dates": dates,
            "prices": prices,
            "unit": "USD/mt",
            "stats": {
                "latest_price": latest,
                "earliest_price": oldest,
                "period_change_pct": change_pct,
                "high": max(prices),
                "low": min(prices),
                "trend_direction": trend,
            },
        }

    # ── Collect weather data ──
    weather = get_weather_monthly(start_date=start, end_date=end)
    months = weather.get("months", [])
    t2m = weather.get("T2M", [])
    precip = weather.get("PRECTOTCORR", [])
    t2m_max = weather.get("T2M_MAX", [])

    weather_stats = {}
    if t2m:
        weather_stats["avg_temp_C"] = round(sum(t2m) / len(t2m), 1)
        weather_stats["total_precip_mm"] = round(sum(precip), 1)
        weather_stats["peak_temp_C"] = round(max(t2m_max), 1) if t2m_max else None
        weather_stats["heat_stress_months"] = sum(1 for t in t2m_max if t > 35)
        weather_stats["drought_months"] = sum(1 for p in precip if p < 30)
        weather_stats["months_covered"] = len(months)

    # ── Build text summary ──
    summary_lines = [
        f"Market overview for wheat, maize, grape ({start[:4]}-{end[:4]})",
        "",
    ]
    for crop in crop_names:
        s = price_data[crop].get("stats", {})
        if s:
            summary_lines.append(
                f"- {crop}: latest {s.get('latest_price')} USD/mt, "
                f"period change {s.get('period_change_pct')}%, "
                f"trend {s.get('trend_direction')}, "
                f"range {s.get('low')}–{s.get('high')} USD/mt"
            )
    if weather_stats:
        summary_lines.append("")
        summary_lines.append(
            f"Weather ({months[0] if months else '?'} to {months[-1] if months else '?'}): "
            f"avg {weather_stats.get('avg_temp_C')}°C, "
            f"total precip {weather_stats.get('total_precip_mm')} mm, "
            f"peak {weather_stats.get('peak_temp_C')}°C, "
            f"{weather_stats.get('heat_stress_months')} heat-stress months, "
            f"{weather_stats.get('drought_months')} drought months"
        )

    return JSONResponse(content={
        "endpoint": "/agent/market-overview",
        "period": {"start": start, "end": end},
        "prices": price_data,
        "weather": {
            "months": months,
            "PRECTOTCORR": precip,
            "T2M": t2m,
            "T2M_MAX": t2m_max,
            "stats": weather_stats,
        },
        "summary": "\n".join(summary_lines),
    })


# ─── Run ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
