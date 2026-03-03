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
"""

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

from config import CROP_CONFIG, DEFAULT_CROP, FRANCE_BBOX

from services.s2_pc import get_ndvi_stats, get_s2_overlay_png
from services.clms_wms import get_crop_type_overlay
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


# ─── Run ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
