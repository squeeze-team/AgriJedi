/**
 * AgriIntel Frontend — main.js
 *
 * Connects to the FastAPI backend and renders:
 *   - Leaflet map with CLMS crop types overlay
 *   - Weather time-series chart (Chart.js)
 *   - Price time-series chart (Chart.js)
 *   - Yield & price prediction cards
 */

// ─── Config ──────────────────────────────────────────────────────
const API_BASE = "http://localhost:8000";

const CLMS_WMS_URL = "https://geoserver.vlcc.geoville.com/geoserver/ows";
const CLMS_LAYER  = "HRL_CPL:CTY_S2021";

// ─── Leaflet map ─────────────────────────────────────────────────
const map = L.map("map").setView([46.6, 2.5], 6);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 18,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

// CLMS Crop Types WMS overlay
const cropWms = L.tileLayer.wms(CLMS_WMS_URL, {
  layers: CLMS_LAYER,
  format: "image/png",
  transparent: true,
  version: "1.3.0",
  opacity: 0.55,
}).addTo(map);

L.control.layers(
  {},
  { "Crop Types 2021 (CLMS)": cropWms },
  { collapsed: false }
).addTo(map);

// Legend (GetLegendGraphic)
const legendDiv = L.control({ position: "bottomright" });
legendDiv.onAdd = function () {
  const div = L.DomUtil.create("div", "map-legend");
  div.innerHTML =
    '<h4>Crop Types 2021</h4>' +
    '<img src="' + CLMS_WMS_URL +
    '?service=WMS&request=GetLegendGraphic&version=1.3.0&format=image/png&layer=' +
    encodeURIComponent(CLMS_LAYER) + '" alt="legend" />';
  return div;
};
legendDiv.addTo(map);

// ─── Charts ──────────────────────────────────────────────────────
let weatherChart = null;
let priceChart = null;

async function loadWeatherChart() {
  const ctx = document.getElementById("weatherChart").getContext("2d");

  try {
    const resp = await fetch(`${API_BASE}/weather/france?start=20230101&end=20241231`);
    const data = await resp.json();
    renderWeatherChart(ctx, data);
  } catch {
    // Fallback demo data when backend is not running
    renderWeatherChart(ctx, demoPrecipData());
  }
}

function renderWeatherChart(ctx, data) {
  if (weatherChart) weatherChart.destroy();
  weatherChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: data.months,
      datasets: [
        {
          label: "Precipitation (mm)",
          data: data.PRECTOTCORR,
          backgroundColor: "rgba(37,99,235,0.5)",
          yAxisID: "y",
          order: 2,
        },
        {
          label: "Temp Mean (°C)",
          data: data.T2M,
          type: "line",
          borderColor: "#ea580c",
          backgroundColor: "rgba(234,88,12,0.1)",
          fill: true,
          tension: 0.3,
          yAxisID: "y1",
          order: 1,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: "top" } },
      scales: {
        y:  { position: "left",  title: { display: true, text: "Precip (mm)" } },
        y1: { position: "right", title: { display: true, text: "Temp (°C)" }, grid: { drawOnChartArea: false } },
      },
    },
  });
}

async function loadPriceChart() {
  const ctx = document.getElementById("priceChart").getContext("2d");
  // Use demo data (backend not always available)
  const months = [];
  const prices = [];
  let p = 340;
  for (let y = 2022; y <= 2024; y++) {
    for (let m = 1; m <= 12; m++) {
      months.push(`${y}-${String(m).padStart(2,"0")}`);
      p += (Math.random() - 0.52) * 15;
      p = Math.max(200, Math.min(500, p));
      prices.push(Math.round(p));
    }
  }

  if (priceChart) priceChart.destroy();
  priceChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: months,
      datasets: [{
        label: "Wheat Price (USD/mt)",
        data: prices,
        borderColor: "#16a34a",
        backgroundColor: "rgba(22,163,74,0.08)",
        fill: true, tension: 0.3,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: "top" } },
      scales: { y: { title: { display: true, text: "USD / metric ton" } } },
    },
  });
}

// ─── Predictions ─────────────────────────────────────────────────
async function runPredictions() {
  const crop = document.getElementById("cropSelect").value;

  document.getElementById("yieldLoading").style.display = "flex";
  document.getElementById("yieldResult").style.display = "none";
  document.getElementById("priceLoading").style.display = "flex";
  document.getElementById("priceResult").style.display = "none";

  // Yield
  try {
    const yr = await fetch(`${API_BASE}/predict/yield?crop=${crop}&country=France`);
    const yd = await yr.json();
    showYield(yd);
  } catch {
    showYield(demoYieldResult(crop));
  }

  // Price
  try {
    const pr = await fetch(`${API_BASE}/predict/price?crop=${crop}`);
    const pd = await pr.json();
    showPrice(pd);
  } catch {
    showPrice(demoPriceResult(crop));
  }
}

function showYield(d) {
  document.getElementById("yieldLoading").style.display = "none";
  const el = document.getElementById("yieldResult");
  el.style.display = "block";

  const sign = d.anomaly_percent >= 0 ? "+" : "";
  const color = d.anomaly_percent >= 0 ? "var(--green)" : "var(--red)";

  el.innerHTML = `
    <div class="pred-value" style="color:${color}">${d.predicted_yield_ton_ha} t/ha</div>
    <div class="pred-detail">
      Anomaly: <strong style="color:${color}">${sign}${d.anomaly_percent}%</strong>
      &nbsp;|&nbsp; Confidence: ${(d.confidence * 100).toFixed(0)}%
    </div>
    <div class="explanation">${d.explanation}</div>
  `;
}

function showPrice(d) {
  document.getElementById("priceLoading").style.display = "none";
  const el = document.getElementById("priceResult");
  el.style.display = "block";

  const badgeClass = d.direction === "Up" ? "badge-up"
                   : d.direction === "Down" ? "badge-down"
                   : "badge-flat";
  const arrow = d.direction === "Up" ? "↑" : d.direction === "Down" ? "↓" : "→";

  el.innerHTML = `
    <div class="pred-value">
      <span class="badge ${badgeClass}">${arrow} ${d.direction}</span>
      <span style="font-size:18px;margin-left:10px;">${(d.probability * 100).toFixed(0)}% confidence</span>
    </div>
    <div class="pred-detail" style="margin-top:8px;">
      Last: $${d.price_last_usd_mt}/mt → Forecast: $${d.price_forecast_usd_mt}/mt
      (${d.change_percent >= 0 ? "+" : ""}${d.change_percent}%)
    </div>
    <div class="explanation">${d.explanation}</div>
  `;
}

// ─── Demo / fallback data ────────────────────────────────────────
function demoPrecipData() {
  const months = [];
  const precip = [];
  const temp = [];
  for (let y = 2023; y <= 2024; y++) {
    for (let m = 1; m <= 12; m++) {
      months.push(`${y}-${String(m).padStart(2,"0")}`);
      precip.push(Math.round(40 + Math.random() * 80));
      temp.push(Math.round((5 + 12 * Math.sin((m - 1) / 12 * Math.PI)) * 10) / 10);
    }
  }
  return { months, PRECTOTCORR: precip, T2M: temp, T2M_MAX: temp.map(t => t + 5) };
}

function demoYieldResult(crop) {
  return {
    crop,
    country: "France",
    predicted_yield_ton_ha: crop === "wheat" ? 6.85 : crop === "maize" ? 8.92 : 6.20,
    anomaly_percent: -2.15,
    confidence: 0.75,
    explanation: "Lower rainfall + NDVI anomaly → likely lower yield (demo mode — backend not connected).",
  };
}

function demoPriceResult(crop) {
  return {
    crop,
    direction: "Up",
    probability: 0.72,
    price_last_usd_mt: 255,
    price_forecast_usd_mt: 268,
    change_percent: 5.1,
    explanation: "Lower yield forecast → upward price pressure (demo mode — backend not connected).",
  };
}

// ─── Init ────────────────────────────────────────────────────────
loadWeatherChart();
loadPriceChart();
