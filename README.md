# 🌾 AgriIntel — France Wheat Yield & Price Prediction Demo

A hackathon-ready system that predicts national wheat yield anomalies and 3-month price direction for France by combining satellite, climate, yield, and commodity data.

---

## Architecture

```
Sentinel-2 (NDVI)  ──┐
CLMS Crop Types    ──┤
NASA POWER Weather ──┼──▶ Feature Engineering ──▶ Yield Model ──▶ Price Model
FAOSTAT Yields     ──┤                                              │
World Bank Prices  ──┘                                     API + Frontend
```

## Quick Start

### 1. Install dependencies

```bash
cd agri-demo/backend
pip install -r requirements.txt
```

### 2. Run the backend

```bash
cd agri-demo/backend
python app.py
# or: uvicorn app:app --reload --port 8000
```

### 3. Open the frontend

Open `agri-demo/frontend/index.html` in a browser.  
The frontend works **standalone with demo data** (no backend required) and will use the live API when available.

---

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Health check |
| `/crops` | GET | List available crops |
| `/map/overlay?bbox=...&date=...` | GET | Sentinel-2 + CLMS composite PNG |
| `/weather/france?start=...&end=...` | GET | Monthly weather aggregates |
| `/predict/yield?crop=wheat&country=France` | GET | Yield anomaly prediction |
| `/predict/price?crop=wheat` | GET | 3-month price direction forecast |

---

## Data Sources

| Layer | Source | Type |
|---|---|---|
| Crop Distribution | [CLMS HRL Croplands 2021](https://land.copernicus.eu/) | WMS |
| Vegetation (NDVI) | [Sentinel-2 L2A via Planetary Computer](https://planetarycomputer.microsoft.com/) | COG |
| Weather & Hydrology | [NASA POWER](https://power.larc.nasa.gov/) | REST API |
| Yield Statistics | [FAOSTAT](https://www.fao.org/faostat/) | REST API |
| Commodity Prices | [World Bank Pink Sheet](https://www.worldbank.org/en/research/commodity-markets) | Excel |

---

## Extending to Other Crops

Edit `backend/config.py` → `CROP_CONFIG` dictionary. Each entry defines:

- FAOSTAT item code
- Growing season months
- Price series name
- NDVI peak months

No structural changes needed — just switch the `crop` query parameter.

---

## Project Structure

```
agri-demo/
├── backend/
│   ├── app.py                  # FastAPI application
│   ├── config.py               # Crop configs, API URLs, constants
│   ├── requirements.txt
│   ├── services/
│   │   ├── s2_pc.py            # Sentinel-2 via Planetary Computer
│   │   ├── clms_wms.py         # CLMS crop types WMS
│   │   ├── weather_power.py    # NASA POWER weather
│   │   ├── faostat.py          # Historical yield data
│   │   └── prices_worldbank.py # Commodity price data
│   └── features/
│       ├── build_features.py   # Unified feature vector builder
│       └── models.py           # Yield & price prediction models
└── frontend/
    ├── index.html              # Leaflet map + Chart.js dashboard
    └── main.js                 # API integration & rendering
```

---

## Demo Narrative

> "We combine satellite vegetation health, national crop distribution,
> climate stress indicators, and historical production data to forecast
> wheat yield and price trends for France.
>
> Lower rainfall and NDVI anomaly indicate yield pressure,
> which historically correlates with upward price movements."

---

## License

MIT — built for educational and hackathon use.
