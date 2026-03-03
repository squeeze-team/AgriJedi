"""
Prediction models — Yield anomaly & price direction forecasting.

For the hackathon demo these are lightweight rule-based / linear models.
They can be swapped for trained scikit-learn or XGBoost models later.
"""

from __future__ import annotations

import numpy as np

from config import CROP_CONFIG


# ─── Yield prediction (Ridge-style linear heuristic) ─────────────

def predict_yield(features: dict, crop: str = "wheat") -> dict:
    """
    Predict national wheat yield anomaly (% vs 5-year mean).

    Uses a simple weighted-feature approach:
        anomaly ≈ w1·drought_proxy + w2·ndvi_anomaly + w3·heatwave_penalty

    Returns
    -------
    dict with predicted_yield, anomaly_percent, confidence, explanation.
    """
    # Weights (tuned heuristically for the demo)
    w_drought = 8.0    # rain shortfall → yield drop
    w_ndvi = 15.0      # vegetation health signal
    w_heat = -0.3      # each heatwave day subtracts ~0.3 %

    drought = features.get("drought_proxy") or 0.0
    ndvi_anom = features.get("ndvi_anomaly_vs_avg") or 0.0
    heatwave = features.get("heatwave_days") or 0
    yield_5yr = features.get("yield_5yr_avg") or 7.0  # fallback

    anomaly_pct = (
        w_drought * drought
        + w_ndvi * ndvi_anom
        + w_heat * heatwave
    )
    anomaly_pct = float(np.clip(anomaly_pct, -30, 30))

    predicted_yield = yield_5yr * (1 + anomaly_pct / 100)

    # Confidence heuristic based on data availability
    available = sum(
        1 for k in ["drought_proxy", "ndvi_anomaly_vs_avg", "heatwave_days", "yield_5yr_avg"]
        if features.get(k) is not None
    )
    confidence = round(0.25 * available, 2)  # 0.25 – 1.00

    # Explanation
    explanations = []
    if drought < -0.10:
        explanations.append(f"Rainfall deficit ({drought:+.1%}) suggests drought stress")
    elif drought > 0.10:
        explanations.append(f"Above-average rainfall ({drought:+.1%}) is favourable")

    if ndvi_anom < -0.05:
        explanations.append(f"NDVI below normal ({ndvi_anom:+.3f}) indicates weaker vegetation")
    elif ndvi_anom > 0.05:
        explanations.append(f"NDVI above normal ({ndvi_anom:+.3f}) indicates healthy canopy")

    if heatwave > 5:
        explanations.append(f"{heatwave} heatwave days may have stressed crops")

    if not explanations:
        explanations.append("Conditions are close to the historical average")

    return {
        "crop": crop,
        "country": "France",
        "predicted_yield_ton_ha": round(predicted_yield, 2),
        "anomaly_percent": round(anomaly_pct, 2),
        "confidence": confidence,
        "explanation": "; ".join(explanations),
        "features_used": features,
    }


# ─── Price direction prediction (AR(1) + yield shock) ────────────

def predict_price(features: dict, crop: str = "wheat") -> dict:
    """
    Forecast 3-month wheat price direction.

    Simple model:
        price_next ≈ a·price_last + b·yield_anomaly + c·weather_anomaly

    Returns
    -------
    dict with direction, probability, explanation.
    """
    a = 0.92   # autoregressive momentum
    b = -1.5   # negative yield anomaly → higher price
    c = -0.8   # drought → higher price

    price_last = features.get("price_lag_1") or 260.0
    yield_anom = features.get("yield_anomaly_pct") or 0.0
    drought = features.get("drought_proxy") or 0.0

    # Predicted next price level
    price_next = a * price_last + b * yield_anom + c * drought * 100

    change_pct = (price_next - price_last) / (price_last + 1e-6) * 100

    if change_pct > 3:
        direction = "Up"
    elif change_pct < -3:
        direction = "Down"
    else:
        direction = "Flat"

    # Pseudo-probability (sigmoid of absolute change)
    prob = float(1 / (1 + np.exp(-abs(change_pct) / 5)))
    prob = round(max(0.50, min(prob, 0.95)), 2)

    # Explanation
    parts = []
    if yield_anom < -2:
        parts.append(f"Lower-than-average yield ({yield_anom:+.1f}%) creates upward price pressure")
    elif yield_anom > 2:
        parts.append(f"Above-average yield ({yield_anom:+.1f}%) eases price pressure")

    if drought < -0.10:
        parts.append("Drought conditions historically push commodity prices higher")
    elif drought > 0.10:
        parts.append("Adequate rainfall supports stable supply and prices")

    if not parts:
        parts.append("Market conditions suggest a stable price outlook")

    return {
        "crop": crop,
        "direction": direction,
        "probability": prob,
        "price_last_usd_mt": round(price_last, 2),
        "price_forecast_usd_mt": round(price_next, 2),
        "change_percent": round(change_pct, 2),
        "explanation": "; ".join(parts),
        "features_used": features,
    }
