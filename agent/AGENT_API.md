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
      "yield_index": 1.19,
      "yield_index_label": "Normal (off-season)",
      "ndvi_baseline_used": 0.318,
      "optimal_ndvi_range": [0.70, 0.85],
      "peak_months": [4, 5],
      "observation_note": "Wheat is harvested by July...",
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
  "crop_profiles": {
    "<crop_group>": {
      "peak_months": [4, 5],
      "peak_ndvi_range": [0.70, 0.85],
      "summer_ndvi_range": [0.20, 0.50],
      "optimal_ndvi_range": [0.70, 0.85],
      "stress_threshold": 0.55,
      "baseline_by_month": {"1": 0.25, "2": 0.30, "...": "...monthly NDVI reference"}
    }
  },
  "summary": "string — multi-line text summary for LLM context"
}
```

### Crop Phenology Profiles (`crop_profiles`)

The response includes a `crop_profiles` object with full phenological reference data for every crop group. This allows agents to reason about whether an observation window is appropriate, cross-check baselines, and assess stress levels independently.

```json
{
  "wheat": {
    "peak_months": [4, 5],
    "peak_ndvi_range": [0.70, 0.85],
    "summer_ndvi_range": [0.20, 0.50],
    "optimal_ndvi_range": [0.70, 0.85],
    "stress_threshold": 0.55,
    "baseline_by_month": {
      "1": 0.25, "2": 0.30, "3": 0.50, "4": 0.72, "5": 0.78,
      "6": 0.55, "7": 0.30, "8": 0.22, "9": 0.20, "10": 0.20,
      "11": 0.22, "12": 0.24
    }
  },
  "maize": {
    "peak_months": [7, 8],
    "peak_ndvi_range": [0.75, 0.90],
    "summer_ndvi_range": [0.65, 0.85],
    "optimal_ndvi_range": [0.75, 0.90],
    "stress_threshold": 0.55,
    "baseline_by_month": {
      "1": 0.10, "2": 0.10, "3": 0.12, "4": 0.15, "5": 0.30, "6": 0.55,
      "7": 0.78, "8": 0.82, "9": 0.65, "10": 0.35, "11": 0.15, "12": 0.10
    }
  },
  "grape": {
    "peak_months": [7, 8],
    "peak_ndvi_range": [0.45, 0.65],
    "summer_ndvi_range": [0.40, 0.65],
    "optimal_ndvi_range": [0.50, 0.65],
    "stress_threshold": 0.30,
    "baseline_by_month": {
      "1": 0.18, "2": 0.18, "3": 0.22, "4": 0.32, "5": 0.42, "6": 0.50,
      "7": 0.55, "8": 0.56, "9": 0.48, "10": 0.35, "11": 0.22, "12": 0.18
    }
  },
  "other_cereal": {
    "peak_months": [4, 5],
    "peak_ndvi_range": [0.65, 0.80],
    "summer_ndvi_range": [0.18, 0.45],
    "optimal_ndvi_range": [0.65, 0.80],
    "stress_threshold": 0.50,
    "baseline_by_month": {
      "1": 0.22, "2": 0.28, "3": 0.48, "4": 0.68, "5": 0.72,
      "6": 0.48, "7": 0.25, "8": 0.20, "9": 0.18, "10": 0.18,
      "11": 0.20, "12": 0.22
    }
  },
  "grassland": {
    "peak_months": [5, 6],
    "peak_ndvi_range": [0.55, 0.75],
    "summer_ndvi_range": [0.40, 0.70],
    "optimal_ndvi_range": [0.55, 0.75],
    "stress_threshold": 0.30,
    "baseline_by_month": {
      "1": 0.30, "2": 0.32, "3": 0.42, "4": 0.55, "5": 0.62, "6": 0.60,
      "7": 0.50, "8": 0.48, "9": 0.50, "10": 0.45, "11": 0.35, "12": 0.30
    }
  },
  "other": {
    "peak_months": [6, 7],
    "peak_ndvi_range": [0.55, 0.80],
    "summer_ndvi_range": [0.35, 0.70],
    "optimal_ndvi_range": [0.55, 0.80],
    "stress_threshold": 0.30,
    "baseline_by_month": {
      "1": 0.18, "2": 0.20, "3": 0.30, "4": 0.45, "5": 0.55, "6": 0.62,
      "7": 0.60, "8": 0.50, "9": 0.38, "10": 0.25, "11": 0.20, "12": 0.18
    }
  }
}
```

#### Profile Fields

| Field                | Description                                                                 |
|----------------------|-----------------------------------------------------------------------------|
| `peak_months`        | Month numbers (1-12) when canopy cover is at maximum                        |
| `peak_ndvi_range`    | `[low, high]` — expected NDVI during peak months for a healthy crop         |
| `summer_ndvi_range`  | `[low, high]` — expected NDVI during June–September                         |
| `optimal_ndvi_range` | `[low, high]` — NDVI that indicates the crop is in good condition           |
| `stress_threshold`   | NDVI below this (during peak season) indicates definite crop stress         |
| `baseline_by_month`  | Monthly reference NDVI (1=Jan … 12=Dec), used to compute `yield_index`      |

> **How `yield_index` is computed:** the observation window months are averaged from `baseline_by_month`, then `yield_index = ndvi_mean / avg_baseline`. For example, wheat observed in June–September: baseline = avg(0.55, 0.30, 0.22, 0.20) = 0.318; if NDVI mean = 0.38, then yield_index = 0.38 / 0.318 = 1.19.

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

- **`yield_index`** — Ratio of current NDVI mean to the **phenology-aware monthly baseline** for that crop. The baseline varies by month — e.g. wheat baseline in July (post-harvest) is ~0.30, while maize baseline in July (peak growth) is ~0.78. A value of 1.03 means vegetation health is 3% above the expected seasonal baseline.
- **`yield_index_label`** — Human-readable label that accounts for whether the observation falls in the crop's peak season or off-season. Off-season labels include suffixes like "(off-season)" or "(may be post-harvest)".
- **`ndvi_baseline_used`** — The actual monthly-averaged NDVI baseline used for this crop in the observation window. Lets the agent verify the index calculation.
- **`optimal_ndvi_range`** — The NDVI range `[low, high]` that indicates healthy canopy during the crop's peak growth period.
- **`peak_months`** — Month numbers when this crop reaches maximum canopy cover (e.g. `[4, 5]` = April-May for wheat, `[7, 8]` = July-August for maize).
- **`observation_note`** — (optional) Plain-text warning when the observation window doesn't align with the crop's peak season. **Agents should pay attention to this field** — it explains why a yield index might be misleading.
- **`yield_prediction.predicted_yield_t_ha`** — Forecasted yield in metric tons per hectare, calculated as: `(5yr_avg + trend) × yield_index`.
- **`yield_prediction.anomaly_vs_5yr_pct`** — Percentage deviation from the 5-year average yield.
- **`yield_prediction.confidence`** — 0.0–1.0 score. Drops to 0.5 when observation is off-season for the crop (e.g. wheat in summer). Agents should weight predictions accordingly.
- **`yield_prediction.confidence_note`** — (optional) Explanation of why confidence is reduced.
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
4. **Check phenology alignment**: Always check `peak_months` and `observation_note`. If the observation window is off-season for a crop (e.g. wheat in July), the `yield_index` reflects stubble/cover crops, NOT crop health. In such cases, `yield_prediction.confidence` will be reduced.
5. **Combine insights**: If `yield_index < 1.0` during **peak season** and `weather.stats.heat_stress_months > 3`, the region is likely experiencing drought stress. Cross-reference with `prices.stats.trend_direction` to assess market impact.
6. **All data is JSON** — no image endpoints are needed for analytical reasoning.

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
