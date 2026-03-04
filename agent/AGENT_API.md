# AgriIntel Agent API Reference

> Base URL: `http://localhost:8000`

This document describes the two **agent-oriented** endpoints designed for AI agent consumption. Both return structured JSON with a `summary` field containing a human-readable text overview suitable for LLM context.

---

## 1. GET `/agent/yield-analysis`

**Purpose:** Given a geographic bounding box, return per-crop NDVI health analysis and yield forecasts (in tons/hectare) for the upcoming season.

### Query Parameters

| Parameter | Type   | Required | Default                      | Description                                       |
|-----------|--------|----------|------------------------------|---------------------------------------------------|
| `bbox`    | string | No       | `4.67,44.71,4.97,45.01`     | Bounding box: `west,south,east,north` in EPSG:4326 |
| `date`    | string | No       | `2025-06-01/2025-09-01`     | Sentinel-2 date range (`YYYY-MM-DD/YYYY-MM-DD`)   |

### Supported Regions (preset bounding boxes)

| Region         | bbox                         |
|----------------|------------------------------|
| Rhône Valley   | `4.67,44.71,4.97,45.01`     |
| Beauce         | `1.20,48.00,1.80,48.40`     |
| Champagne      | `3.50,48.80,4.30,49.30`     |
| Bordeaux       | `-0.80,44.70,-0.20,45.10`   |

> You may specify any custom bbox within France. Yield forecasts are available when the bbox overlaps a supported département (Drôme, Ardèche, Isère, Rhône, Eure-et-Loir, Loiret, Marne, Aube, Gironde, Bouches-du-Rhône, Vaucluse, Hérault).

### Response Schema

```json
{
  "endpoint": "/agent/yield-analysis",
  "bbox": [4.67, 44.71, 4.97, 45.01],
  "date_range": "2025-06-01/2025-09-01",
  "total_classified_pixels": 160000,
  "crops": {
    "<crop_group>": {
      "label": "string — human-readable crop description",
      "pixel_count": 32480,
      "area_pct": 20.3,
      "ndvi_mean": 0.38,
      "ndvi_std": 0.14,
      "ndvi_median": 0.36,
      "ndvi_p25": 0.28,
      "ndvi_p75": 0.47,
      "yield_index": 0.85,
      "yield_index_label": "Below average",
      "yield_prediction": {
        "predicted_yield_t_ha": 4.98,
        "target_year": 2025,
        "anomaly_vs_5yr_pct": -15.0,
        "method": "agreste_trend_plus_ndvi",
        "confidence": 1.0,
        "explanation": "string — full reasoning",
        "avg_5yr": 5.86,
        "trend": 0.004,
        "history": {"2020": 5.67, "2021": 5.95, "2022": 6.2, "2023": 5.59, "2024": 5.87},
        "departements": ["Drôme", "Isère", "Ardèche"]
      }
    }
  },
  "summary": "string — multi-line text summary for LLM context"
}
```

### Crop Groups

| Group          | Includes                                    |
|----------------|---------------------------------------------|
| `wheat`        | Common wheat, Durum wheat                   |
| `maize`        | Grain maize, Silage maize                   |
| `grape`        | Vineyards                                   |
| `other_cereal` | Barley, Oats, Rye, etc.                    |
| `grassland`    | Temporary + Permanent grassland             |
| `other`        | Sunflower, Rapeseed, Vegetables, etc.       |

> `yield_prediction` is present for `wheat`, `maize`, and `grape` only. Other groups have `yield_prediction: null`.

### Key Fields Explained

- **`yield_index`** — Ratio of current NDVI mean to the 5-year NDVI baseline for that crop. A value of 1.05 means vegetation health is 5% above the historical average.
- **`yield_prediction.predicted_yield_t_ha`** — Forecasted yield in metric tons per hectare, calculated as: `(5yr_avg + trend) × yield_index`.
- **`yield_prediction.anomaly_vs_5yr_pct`** — Percentage deviation from the 5-year average yield.
- **`yield_prediction.history`** — Actual Agreste-sourced département yields for the past 5 years.

### Example Request

```
GET /agent/yield-analysis?bbox=4.67,44.71,4.97,45.01&date=2025-06-01/2025-09-01
```

---

## 2. GET `/agent/market-overview`

**Purpose:** Return price history for wheat, maize, and grape alongside France weather trends, enabling market analysis and supply-side reasoning.

### Query Parameters

| Parameter | Type   | Required | Default      | Description                       |
|-----------|--------|----------|--------------|-----------------------------------|
| `start`   | string | No       | `20230101`   | Weather period start (`yyyyMMdd`) |
| `end`     | string | No       | `20251231`   | Weather period end (`yyyyMMdd`)   |

> Price data always covers the full available range (Jan 2022 – Jan 2026) regardless of the start/end parameters. The start/end parameters control weather data filtering only.

### Response Schema

```json
{
  "endpoint": "/agent/market-overview",
  "period": {"start": "20230101", "end": "20251231"},
  "prices": {
    "wheat": {
      "dates": ["2022-01", "2022-02", "..."],
      "prices": [326.08, 347.50, "..."],
      "unit": "USD/mt",
      "stats": {
        "latest_price": 169.25,
        "earliest_price": 326.08,
        "period_change_pct": -48.1,
        "high": 444.16,
        "low": 155.12,
        "trend_direction": "stable"
      }
    },
    "maize": { "..." : "same structure" },
    "grape": { "..." : "same structure" }
  },
  "weather": {
    "months": ["2023-01", "2023-02", "..."],
    "PRECTOTCORR": [62.3, 38.7, "..."],
    "T2M": [5.1, 6.3, "..."],
    "T2M_MAX": [12.4, 14.8, "..."],
    "stats": {
      "avg_temp_C": 13.4,
      "total_precip_mm": 1980.5,
      "peak_temp_C": 37.8,
      "heat_stress_months": 4,
      "drought_months": 3,
      "months_covered": 36
    }
  },
  "summary": "string — multi-line text summary for LLM context"
}
```

### Price Data Details

| Crop   | Source                         | Unit    | Coverage             |
|--------|-------------------------------|---------|----------------------|
| wheat  | FRED / IMF (PWHEAMTUSDM)      | USD/mt  | Jan 2022 – Jan 2026 |
| maize  | FRED / IMF (PMAIZMTUSDM)      | USD/mt  | Jan 2022 – Jan 2026 |
| grape  | OIV / France contract proxy   | USD/mt  | Jan 2022 – Jan 2026 |

### Weather Variables

| Variable        | Description                          | Unit    |
|-----------------|--------------------------------------|---------|
| `PRECTOTCORR`   | Total monthly precipitation          | mm      |
| `T2M`           | Mean monthly temperature             | °C      |
| `T2M_MAX`       | Peak monthly temperature             | °C      |

### Computed Weather Stats

| Field                 | Description                                          |
|-----------------------|------------------------------------------------------|
| `avg_temp_C`          | Average temperature across all months in range        |
| `total_precip_mm`     | Sum of precipitation across all months in range       |
| `peak_temp_C`         | Highest peak temperature recorded                     |
| `heat_stress_months`  | Count of months where peak temperature > 35°C         |
| `drought_months`      | Count of months where precipitation < 30 mm           |

### Example Request

```
GET /agent/market-overview?start=20230101&end=20251231
```

---

## Usage Notes for AI Agents

1. **Start with `/agent/yield-analysis`** to assess crop health and yield outlook for a specific region.
2. **Then call `/agent/market-overview`** to understand the price context and weather conditions.
3. **Use the `summary` field** in each response as pre-formatted context — it provides a concise text overview suitable for inclusion in LLM prompts.
4. **Combine insights**: If `yield_index < 1.0` (poor vegetation) and `weather.stats.heat_stress_months > 3`, the region is likely experiencing drought stress. Cross-reference with `prices.stats.trend_direction` to assess market impact.
5. **All data is JSON** — no image endpoints are needed for analytical reasoning.

### Recommended Agent Workflow

```
1. Call /agent/yield-analysis?bbox=<target_region>
   → Extract crop yield forecasts and NDVI health status

2. Call /agent/market-overview
   → Extract price trends and weather anomalies

3. Synthesize:
   - Compare yield_prediction.anomaly_vs_5yr_pct with price trend_direction
   - Check weather.stats for stress indicators
   - Generate advisory or risk assessment
```

### Error Handling

| HTTP Code | Meaning                                      |
|-----------|----------------------------------------------|
| 200       | Success — JSON response                      |
| 400       | Invalid bbox format or parameter              |
| 500       | Internal server error (service failure)       |

All responses include `Content-Type: application/json`.
