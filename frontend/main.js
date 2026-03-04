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

function getLast24MonthRange() {
  const now = new Date();
  const end = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(now.getDate()).padStart(2, "0")}`;
  const start = new Date(now);
  start.setMonth(start.getMonth() - 24);
  const startStr = `${start.getFullYear()}${String(start.getMonth() + 1).padStart(2, "0")}01`;
  return { start: startStr, end };
}

async function loadWeatherChart() {
  const ctx = document.getElementById("weatherChart").getContext("2d");
  const { start, end } = getLast24MonthRange();

  try {
    const resp = await fetch(`${API_BASE}/weather/france?start=${start}&end=${end}`);
    const data = await resp.json();
    if (data.months && data.months.length > 0) {
      renderWeatherChart(ctx, data);
    } else {
      renderWeatherChart(ctx, demoPrecipData());
    }
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
  const crop = document.getElementById("cropSelect").value;
  const ctx = document.getElementById("priceChart").getContext("2d");

  let months, prices, label;

  try {
    const resp = await fetch(`${API_BASE}/prices/history?crop=${crop}`);
    const data = await resp.json();
    if (data.dates && data.dates.length > 0) {
      months = data.dates;
      prices = data.prices;
      label = `${capitalize(crop)} Price (${data.unit || "USD/mt"})`;  
    } else {
      throw new Error("empty");
    }
  } catch {
    // Fallback demo data
    const demo = demoPriceData(crop);
    months = demo.months;
    prices = demo.prices;
    label = `${capitalize(crop)} Price (USD/mt) — demo`;
  }

  if (priceChart) priceChart.destroy();
  priceChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: months,
      datasets: [{
        label,
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

function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

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
  // Bundled monthly weather matching backend _BUNDLED_WEATHER_MONTHLY
  const data = {
    months: [
      "2024-01","2024-02","2024-03","2024-04","2024-05","2024-06",
      "2024-07","2024-08","2024-09","2024-10","2024-11","2024-12",
      "2025-01","2025-02","2025-03","2025-04","2025-05","2025-06",
      "2025-07","2025-08","2025-09","2025-10","2025-11","2025-12",
    ],
    PRECTOTCORR: [58.0,45.5,50.2,68.7,78.3,38.1,28.5,32.0,52.4,72.8,68.5,74.2,
                  55.8,42.0,60.1,70.5,62.0,40.2,30.5,35.8,55.0,76.0,72.5,68.0],
    T2M:         [4.8,6.9,9.8,12.5,15.9,19.8,23.2,22.5,18.2,13.4,7.9,5.2,
                  4.5,5.9,8.7,11.4,14.8,19.5,22.8,21.9,17.8,13.0,8.0,5.5],
    T2M_MAX:     [11.2,15.3,19.1,23.5,27.0,32.5,37.8,36.2,29.5,22.0,14.8,11.5,
                  10.8,13.5,17.9,21.8,25.5,31.8,37.2,35.5,28.8,21.5,15.2,11.8],
  };
  return data;
}

function demoPriceData(crop) {
  // Bundled price series matching backend _BUNDLED_PRICES (real FRED/IMF data for wheat & maize)
  const series = {
    wheat:  {data: [326.08,347.50,387.67,406.03,444.16,397.65,321.98,323.02,346.32,353.71,344.33,323.65,
             320.10,332.41,309.43,312.81,299.44,282.28,278.62,241.41,229.39,216.46,216.00,229.63,
             226.08,219.24,211.84,208.38,227.43,205.23,183.23,175.51,188.51,197.37,185.73,185.79,
             190.63,190.10,179.61,174.82,196.84,173.19,165.27,159.31,155.12,157.39,169.20,165.63,169.25]},
    maize:  {data: [276.72,292.67,335.93,348.51,344.91,335.72,312.68,293.93,312.55,343.55,320.93,302.24,
             302.84,298.25,284.96,291.18,268.17,266.94,235.27,207.68,223.85,221.90,209.04,207.40,
             198.76,188.95,190.23,190.90,201.02,191.24,177.77,169.30,183.66,189.59,201.31,202.83,
             214.36,221.25,207.75,215.57,204.81,195.72,192.45,183.02,196.15,198.02,201.66,205.32,203.90]},
    grape:  {data: [780,790,805,830,855,870,865,850,840,825,815,810,
             800,795,785,770,755,740,730,710,695,680,670,665,
             660,655,650,645,648,655,660,670,685,690,695,700,
             705,710,715,718,720,725,722,718,712,708,705,710,715]},
  };
  const s = series[crop] || series.wheat;
  const months = [];
  let mi = 0;
  for (let y = 2022; y <= 2026; y++) {
    for (let m = 1; m <= 12; m++) {
      if (mi >= s.data.length) break;
      months.push(`${y}-${String(m).padStart(2, "0")}`);
      mi++;
    }
  }
  return { months: months.slice(0, s.data.length), prices: s.data };
}

function demoYieldResult(crop) {
  return {
    crop,
    country: "France",
    predicted_yield_ton_ha: crop === "wheat" ? 6.85 : crop === "maize" ? 8.92 : 6.00,
    anomaly_percent: crop === "wheat" ? -2.15 : crop === "maize" ? -1.80 : -2.50,
    confidence: 0.75,
    explanation: "Lower rainfall + NDVI anomaly → likely lower yield (demo mode — backend not connected).",
  };
}

function demoPriceResult(crop) {
  const prices = { wheat: [255, 268], maize: [212, 222], grape: [775, 790] };
  const p = prices[crop] || prices.wheat;
  return {
    crop,
    direction: "Up",
    probability: 0.72,
    price_last_usd_mt: p[0],
    price_forecast_usd_mt: p[1],
    change_percent: +(((p[1] - p[0]) / p[0]) * 100).toFixed(1),
    explanation: "Lower yield forecast → upward price pressure (demo mode — backend not connected).",
  };
}

// ─── Satellite Imagery ─────────────────────────────────────────────
let bboxRect = null;

function applyBboxPreset() {
  const sel = document.getElementById("bboxPreset");
  const input = document.getElementById("bboxInput");
  if (sel.value !== "custom") {
    input.value = sel.value;
  }
}

function loadSatelliteViews() {
  const bbox = document.getElementById("bboxInput").value.trim();
  const date = document.getElementById("satDateInput").value.trim();
  const layers = ["rgb", "false_color", "ndvi", "overlay"];

  // Draw bbox rectangle on Leaflet map
  try {
    const [west, south, east, north] = bbox.split(",").map(Number);
    if (bboxRect) map.removeLayer(bboxRect);
    bboxRect = L.rectangle(
      [[south, west], [north, east]],
      { color: "#e11d48", weight: 2, fillOpacity: 0.1, dashArray: "6 4" }
    ).addTo(map);
  } catch (_) { /* ignore parse errors */ }

  layers.forEach(layer => {
    const img = document.getElementById(`sat-${layer}`);
    const ph  = document.getElementById(`ph-${layer}`);

    // Show loading state
    img.style.display = "none";
    ph.textContent = "Loading…";
    ph.style.display = "block";

    const url = `${API_BASE}/satellite/view?bbox=${encodeURIComponent(bbox)}&date=${encodeURIComponent(date)}&layer=${layer}&width=600&height=600`;

    const tmp = new Image();
    tmp.onload = () => {
      img.src = tmp.src;
      img.style.display = "block";
      ph.style.display = "none";
    };
    tmp.onerror = () => {
      ph.textContent = "Failed to load — is the backend running?";
    };
    tmp.src = url;
  });
}

// ─── Crop selector change → reload charts ────────────────────────
document.getElementById("cropSelect").addEventListener("change", () => {
  loadPriceChart();
});

// ─── Init ────────────────────────────────────────────────────────
loadWeatherChart();
loadPriceChart();
