# 🌾 AgroMind — The AI Brain for Agriculture

> **MVP** — Ask a question about any crop in France. AgroMind streams a real-time advisory by chaining satellite imagery, weather risk, yield forecasts, and commodity market signals through a multi-agent AI pipeline — all in one chat interface.

---

## What We Built

AgroMind is an AI-powered agricultural intelligence platform that acts as a **smart brain for agriculture**. It combines satellite remote sensing, weather forecasts, and commodity market signals into a single conversational interface.

Users simply ask questions like *"How is wheat doing in Beauce?"* and receive an explainable advisory covering crop health, yield outlook, price trends, and climate risks.

## The Problem

Modern agriculture suffers from **fragmented and delayed information**:

- **Satellite data is hard to use** — NDVI and crop-type layers exist, but most farmers and traders can't interpret raw raster imagery.
- **Reports arrive too late** — By the time official yield statistics are published, growing conditions have already changed.
- **Disconnected from markets** — Global commodity futures, exchange rates, and supply/demand reports (USDA WASDE) directly affect farm-gate prices, yet this information rarely reaches the field.
- **No unified view** — The causal chain *weather stress → crop damage → yield drop → price spike* is never visible in one place.

## Our Solution

AgroMind connect these signals into a **single AI-driven intelligence system**:

- **Multi-Agent AI Analysis** — A LangGraph pipeline of 7 specialized agents (query analysis → geocoding → yield analysis → market overview → climate risk → bio-monitoring → orchestrator) that streams structured, explainable advisories in real time.
- **Satellite Crop Monitoring** — Sentinel-2 NDVI + Copernicus CLMS crop-type classification, with per-crop phenological baselines that distinguish real stress from natural senescence. Yield index and t/ha predictions per département.
- **Weather Risk Intelligence** — Meteo-France 14-day forecasts (via Open-Meteo) for flood, heat, and drought risk; NASA POWER historical climate for long-term context.
- **Market & Financial Signals** — Wheat/corn futures, EUR/USD, WTI crude oil, US 10Y yield, and USDA WASDE supply/demand regime — all fed into price trend forecasting.
- **Interactive Map & Dashboard** — React + Leaflet map with satellite RGB/NDVI/overlay layers, crop distribution legend, price charts, weather charts, and a risk analysis panel.
- **Conversational Chat Interface** — SSE-streaming chatbot where each agent stage streams progress updates, then delivers a final natural-language advisory with actionable recommendations.

---

## Quick Start

### 1. Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env          # add your OPENROUTER_API_KEY
python app.py                 # runs on http://localhost:8000
```

### 2. Frontend (React)

```bash
cd frontend_react/my-app
npm install
npm run dev                   # runs on http://localhost:5173
```

The legacy `frontend/index.html` still works standalone with demo data.

---

## API Endpoints

All data endpoints use **POST with JSON body**.

| Endpoint | Description |
|---|---|
| `GET /` | Health check |
| `POST /crops` | List available crops |
| `POST /map/overlay` | Sentinel-2 + CLMS composite PNG |
| `POST /satellite/view` | Satellite layer (RGB / false-color / NDVI / overlay) |
| `POST /weather/france` | Monthly weather aggregates (NASA POWER) |
| `POST /predict/yield` | Yield anomaly prediction |
| `POST /predict/price` | 3-month price direction forecast |
| `POST /prices/history` | Monthly commodity price time-series |
| `POST /yield/history` | Annual yield time-series |
| `POST /ndvi/stats` | NDVI summary statistics |
| `POST /chat/stream` | LangGraph multi-agent streaming chatbot (SSE) |
| `POST /analysis/report` | Structured AI risk analysis for a bbox |

**Agent-oriented endpoints** (optimized for LLM consumption):

| Endpoint | Description |
|---|---|
| `POST /agent/yield-analysis` | Per-crop NDVI + yield forecast for a bbox |
| `POST /agent/market-overview` | 3-crop price history + weather trends |
| `POST /agent/market-signals` | Futures, FX, oil, rates, WASDE signals |
| `POST /agent/system-prompt` | Macro context blob for LLM system prompt |
| `POST /market/weekly-chart` | Weekly price series for frontend charts |

---

## Data Sources

| Layer | Source | Type |
|---|---|---|
| Crop Distribution | [Copernicus CLMS HRL Croplands 2021](https://land.copernicus.eu/) | WMS GeoTIFF |
| Vegetation (NDVI) | [Sentinel-2 L2A via Planetary Computer](https://planetarycomputer.microsoft.com/) | COG |
| Weather (historical) | [NASA POWER](https://power.larc.nasa.gov/) | REST API |
| Weather (forecast) | [Meteo-France via Open-Meteo](https://open-meteo.com/) | REST API |
| Yield (national) | [FAOSTAT](https://www.fao.org/faostat/) | REST API |
| Yield (département) | [Agreste](https://agreste.agriculture.gouv.fr/) | Bundled |
| Commodity Prices | [World Bank Pink Sheet](https://www.worldbank.org/en/research/commodity-markets) | Excel |
| Financial Markets | [Yahoo Finance](https://finance.yahoo.com/) (wheat/corn futures, FX, oil, bonds) | API |
| Supply/Demand | USDA WASDE (global stocks-to-use) | Bundled CSV |

---

## Project Structure

```
AgriJedi/
├── backend/
│   ├── app.py                          # FastAPI application (all endpoints)
│   ├── config.py                       # Crop configs, API URLs, constants
│   ├── requirements.txt
│   ├── services/
│   │   ├── s2_pc.py                    # Sentinel-2 via Planetary Computer
│   │   ├── clms_wms.py                 # CLMS crop types WMS
│   │   ├── crop_ndvi_analysis.py       # Per-crop NDVI + yield index pipeline
│   │   ├── agreste.py                  # French département-level yield data
│   │   ├── weather_power.py            # NASA POWER weather
│   │   ├── faostat.py                  # Historical yield data
│   │   ├── prices_worldbank.py         # Commodity price data
│   │   ├── market_finance.py           # Futures, FX, oil, WASDE signals
│   │   ├── chat_langgraph.py           # Simple LangGraph chat service
│   │   ├── agri_agent/                 # Lightweight multi-agent pipeline
│   │   │   ├── types.py               #   AgentState definition
│   │   │   ├── stages.py              #   7 agent stage functions
│   │   │   └── stream.py              #   SSE streaming orchestration
│   │   └── agent_full/                 # Full multi-agent pipeline (advanced)
│   │       ├── core.py                 #   2500+ line agent with geocoding, Meteo-France, etc.
│   │       └── stream.py              #   SSE streaming with fallback
│   ├── features/
│   │   ├── build_features.py           # Unified feature vector builder
│   │   └── models.py                   # Yield & price prediction models
│   ├── data/                           # Bundled market data & system prompts
│   └── scripts/                        # Data download & test utilities
│
├── frontend_react/my-app/              # React + Vite + TypeScript frontend
│   └── src/
│       ├── App.tsx                     # Main dashboard layout
│       └── components/
│           ├── MapPanel.tsx            # Leaflet map with satellite layers
│           ├── ChatBubble.tsx          # Streaming AI chat interface
│           ├── RiskAnalysisPanel.tsx   # AI-driven risk assessment
│           ├── SatelliteSection.tsx    # RGB / NDVI / overlay viewer
│           ├── CropAnalysisSection.tsx # Crop distribution & NDVI stats
│           ├── PriceChartPanel.tsx     # Commodity price charts
│           └── WeatherChartPanel.tsx   # Temperature & precipitation charts
│
├── frontend/                           # Legacy standalone HTML/JS demo
│   ├── index.html
│   └── main.js
│
├── agent/                              # Standalone agent (external orchestration)
│   ├── main.py                         # 2100+ line full agent with LangGraph
│   └── AGENT_API.md                    # Agent API reference documentation
│
└── dev_docs/                           # Design docs & prototypes
```

---

## Supported Regions

Pre-configured bounding boxes for rapid demo:

| Region | Description |
|---|---|
| Beauce | France's breadbasket (Eure-et-Loir, Loiret) |
| Champagne | Major wheat & wine region (Marne, Aube) |
| Rhône Valley | Mixed agriculture (Drôme, Ardèche, Isère, Rhône) |
| Bordeaux | Wine country (Gironde) |
| Provence | Mediterranean crops (Bouches-du-Rhône, Vaucluse, Hérault) |

Any custom bounding box within France is also supported.

---

## Extending to Other Crops

Edit `backend/config.py` → `CROP_CONFIG`. Each entry defines:

- FAOSTAT item code & growing season months
- NDVI peak months & phenological baselines
- Price series name

Currently supports **wheat**, **maize**, and **grape**. No structural changes needed to add more.

---

## License

MIT — built for educational and hackathon use.
