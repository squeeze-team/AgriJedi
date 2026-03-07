function resolveApiBase(): string {
  if (typeof window === 'undefined' || !window.location) {
    return '';
  }

  const { protocol, hostname, port, origin } = window.location;
  const normalizedOrigin = origin.replace(/\/+$/, '');

  // Dev server (Vite) runs on 5173/5174..., while backend stays on 8000.
  if (port && port !== '8000') {
    return `${protocol}//${hostname}:8000`;
  }

  return normalizedOrigin;
}

export const API_BASE = resolveApiBase();

export type Crop = 'wheat' | 'maize' | 'grape';
export type PriceDirection = 'Up' | 'Down' | 'Flat';
export type SatelliteLayer = 'rgb' | 'false_color' | 'ndvi' | 'overlay';

export interface WeatherData {
  months: string[];
  PRECTOTCORR: number[];
  T2M: number[];
}

export interface WeatherForecastDay {
  date: string;
  temp_max_c: number | null;
  temp_min_c: number | null;
  precip_mm: number | null;
  wind_kmh: number | null;
  weather_code: number | null;
}

export interface WeatherForecastData {
  source: string;
  latitude: number;
  longitude: number;
  timezone: string;
  days: WeatherForecastDay[];
}

export interface PriceHistoryData {
  months: string[];
  prices: number[];
  unit: string;
  isDemo?: boolean;
}

export interface MultiPriceHistoryData {
  months: string[];
  unit: string;
  series: Record<Crop, number[]>;
  isDemo?: boolean;
}

export interface YieldPrediction {
  crop: Crop;
  country: string;
  predicted_yield_ton_ha: number;
  anomaly_percent: number;
  confidence: number;
  explanation: string;
}

export interface PricePrediction {
  crop: Crop;
  direction: PriceDirection;
  probability: number;
  price_last_usd_mt: number;
  price_forecast_usd_mt: number;
  change_percent: number;
  explanation: string;
}

export interface CropYieldHistory {
  [year: string]: number;
}

export interface CropYieldPredictionDetail {
  target_year: number;
  predicted_yield_t_ha: number;
  anomaly_vs_5yr_pct: number;
  avg_5yr: number;
  trend: number;
  confidence: number;
  history?: CropYieldHistory;
  departements?: string[];
}

export interface CropAnalysisItem {
  label: string;
  area_pct: number;
  ndvi_mean: number;
  ndvi_median: number;
  ndvi_std: number;
  ndvi_p25: number;
  ndvi_p75: number;
  pixel_count: number;
  yield_index: number | null;
  yield_index_label: string;
  yield_prediction?: CropYieldPredictionDetail;
}

export interface CropAnalysisResponse {
  bbox: string;
  total_classified_pixels: number;
  resolution_px: number;
  item_id?: string;
  error?: string;
  crops: Record<string, CropAnalysisItem>;
}

function capitalize(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function getCropLabel(crop: Crop) {
  return capitalize(crop);
}

function parseBboxString(bbox: string): [number, number, number, number] {
  const values = bbox.split(',').map((v) => Number(v.trim()));
  if (values.length !== 4 || values.some((v) => Number.isNaN(v))) {
    throw new Error('Invalid bbox format');
  }
  return [values[0], values[1], values[2], values[3]];
}

function getLast24MonthRange() {
  const now = new Date();
  const end = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`;
  const start = new Date(now);
  start.setMonth(start.getMonth() - 24);
  const startStr = `${start.getFullYear()}${String(start.getMonth() + 1).padStart(2, '0')}01`;
  return { start: startStr, end };
}

export async function fetchWeather(): Promise<WeatherData> {
  const { start, end } = getLast24MonthRange();
  try {
    const response = await fetch(`${API_BASE}/weather/france`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ start, end }),
    });
    const data = (await response.json()) as Partial<WeatherData>;
    if (data.months && data.months.length > 0 && data.PRECTOTCORR && data.T2M) {
      return data as WeatherData;
    }
    return demoWeatherData();
  } catch {
    return demoWeatherData();
  }
}

export async function fetchWeatherForecast(days = 7): Promise<WeatherForecastData> {
  try {
    const response = await fetch(`${API_BASE}/weather/france/forecast`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ days }),
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = (await response.json()) as Partial<WeatherForecastData>;
    if (data.days && data.days.length > 0) {
      return data as WeatherForecastData;
    }
    return demoWeatherForecast(days);
  } catch {
    return demoWeatherForecast(days);
  }
}

export async function fetchPriceHistory(crop: Crop): Promise<PriceHistoryData> {
  try {
    const response = await fetch(`${API_BASE}/prices/history`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ crop }),
    });
    const data = (await response.json()) as { dates?: string[]; prices?: number[]; unit?: string };
    if (data.dates && data.dates.length > 0 && data.prices) {
      return {
        months: data.dates,
        prices: data.prices,
        unit: data.unit ?? 'USD/mt',
      };
    }
    throw new Error('Empty price history');
  } catch {
    const demo = demoPriceHistory(crop);
    return {
      ...demo,
      unit: 'USD/mt',
      isDemo: true,
    };
  }
}

export async function fetchAllPriceHistory(): Promise<MultiPriceHistoryData> {
  const crops: Crop[] = ['wheat', 'maize', 'grape'];
  const results = await Promise.all(crops.map((crop) => fetchPriceHistory(crop)));

  const monthSet = new Set<string>();
  results.forEach((result) => {
    result.months.forEach((month) => monthSet.add(month));
  });
  const months = Array.from(monthSet).sort();

  const series = {} as Record<Crop, number[]>;
  crops.forEach((crop, index) => {
    const result = results[index];
    const priceByMonth = new Map<string, number>();
    result.months.forEach((month, i) => {
      priceByMonth.set(month, result.prices[i]);
    });
    series[crop] = months.map((month) => {
      const direct = priceByMonth.get(month);
      if (direct != null) {
        return direct;
      }
      const prev = [...priceByMonth.entries()]
        .filter(([m]) => m < month)
        .sort((a, b) => a[0].localeCompare(b[0]))
        .at(-1)?.[1];
      return prev ?? NaN;
    });
  });

  return {
    months,
    unit: results[0]?.unit ?? 'USD/mt',
    isDemo: results.some((result) => result.isDemo),
    series,
  };
}

export async function fetchYieldPrediction(crop: Crop): Promise<YieldPrediction> {
  try {
    const response = await fetch(`${API_BASE}/predict/yield`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ crop, country: 'France' }),
    });
    return (await response.json()) as YieldPrediction;
  } catch {
    return demoYieldPrediction(crop);
  }
}

export async function fetchPricePrediction(crop: Crop): Promise<PricePrediction> {
  try {
    const response = await fetch(`${API_BASE}/predict/price`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ crop }),
    });
    return (await response.json()) as PricePrediction;
  } catch {
    return demoPricePrediction(crop);
  }
}

export async function fetchCropAnalysis(bbox: string, date: string): Promise<CropAnalysisResponse> {
  const response = await fetch(`${API_BASE}/analysis/crop-ndvi`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      bbox: parseBboxString(bbox),
      date,
      resolution: 400,
    }),
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return (await response.json()) as CropAnalysisResponse;
}

export async function fetchSatelliteLayerImage(
  bbox: string,
  date: string,
  layer: SatelliteLayer,
): Promise<string> {
  const response = await fetch(`${API_BASE}/satellite/view`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      bbox: parseBboxString(bbox),
      date,
      layer,
      width: 600,
      height: 600,
    }),
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}

// ──────────────────────────────────────────────
// Analysis Report (AI Agent risk analysis)
// ──────────────────────────────────────────────
export type RecommendedAction = 'sell' | 'hold';

export interface MarketWeatherRisk {
  market_focus_crop?: string;
  latest_price?: number;
  trend_direction?: string;
  period_change_pct?: number;
  weather_risk_score?: number;
  soil_moisture_pct?: number;
  precipitation_mm?: number;
  heat_risk?: number;
  flood_risk?: number;
  [key: string]: string | number | undefined;
}

export interface AnalysisReport {
  crop_type_in_bbox: boolean;
  selected_bbox: [number, number, number, number];
  crop_type: string;
  risk_score: number;                       // 1-5
  'Geospatial & Crop Context': string;
  'Yield & Vegetation Assessment': string;
  'Market & Weather Risk Assessment': MarketWeatherRisk;
  recommended_action: RecommendedAction;
  'Bio-monitor Interpretation': string;
  'Risk Triggers to Watch (next planning horizon)': string;
  [key: string]: string | number | boolean | number[] | MarketWeatherRisk | null;
}

export interface AnalysisReportRequest {
  bbox: string;
  crop?: string;
  date?: string;
  resolution?: number;
}

export async function fetchAnalysisReport(
  bbox: string,
  options?: Omit<AnalysisReportRequest, 'bbox'>,
): Promise<AnalysisReport> {
  const response = await fetch(`${API_BASE}/analysis/report`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      bbox,
      crop: options?.crop,
      date: options?.date,
      resolution: options?.resolution,
    }),
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return (await response.json()) as AnalysisReport;
}

export interface GdacsEuropeEvent {
  id: string;
  title: string;
  hazard: string;
  alert_level: string;
  start_date: string;
  end_date: string;
  country: string;
  url: string;
}

export interface GdacsEuropeEventsResponse {
  feed_ok: boolean;
  all_good: boolean;
  region: string;
  lookback_days: number;
  checked_at: string;
  events: GdacsEuropeEvent[];
  message: string;
}

export async function fetchEuropeGdacsEvents(days = 14, limit = 8): Promise<GdacsEuropeEventsResponse> {
  const response = await fetch(`${API_BASE}/events/gdacs/europe`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ days, limit }),
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return (await response.json()) as GdacsEuropeEventsResponse;
}

function demoWeatherData(): WeatherData {
  return {
    months: [
      '2024-01', '2024-02', '2024-03', '2024-04', '2024-05', '2024-06',
      '2024-07', '2024-08', '2024-09', '2024-10', '2024-11', '2024-12',
      '2025-01', '2025-02', '2025-03', '2025-04', '2025-05', '2025-06',
      '2025-07', '2025-08', '2025-09', '2025-10', '2025-11', '2025-12',
    ],
    PRECTOTCORR: [58.0, 45.5, 50.2, 68.7, 78.3, 38.1, 28.5, 32.0, 52.4, 72.8, 68.5, 74.2, 55.8, 42.0, 60.1, 70.5, 62.0, 40.2, 30.5, 35.8, 55.0, 76.0, 72.5, 68.0],
    T2M: [4.8, 6.9, 9.8, 12.5, 15.9, 19.8, 23.2, 22.5, 18.2, 13.4, 7.9, 5.2, 4.5, 5.9, 8.7, 11.4, 14.8, 19.5, 22.8, 21.9, 17.8, 13.0, 8.0, 5.5],
  };
}

function demoWeatherForecast(days: number): WeatherForecastData {
  const today = new Date();
  const safeDays = Math.max(1, Math.min(days, 10));
  const weatherCodes = [3, 1, 61, 63, 2, 0, 3, 1, 2, 61];
  const maxArr = [11, 13, 14, 12, 10, 9, 11, 13, 14, 12];
  const minArr = [4, 5, 6, 5, 3, 2, 4, 5, 6, 5];
  const precipArr = [1.2, 0.0, 3.5, 6.2, 0.8, 0.0, 2.1, 0.3, 1.8, 4.0];
  const windArr = [17, 14, 20, 23, 16, 13, 18, 15, 14, 19];
  const daysData: WeatherForecastDay[] = [];
  for (let i = 0; i < safeDays; i += 1) {
    const d = new Date(today);
    d.setDate(today.getDate() + i);
    daysData.push({
      date: d.toISOString().slice(0, 10),
      temp_max_c: maxArr[i],
      temp_min_c: minArr[i],
      precip_mm: precipArr[i],
      wind_kmh: windArr[i],
      weather_code: weatherCodes[i],
    });
  }
  return {
    source: 'demo-fallback',
    latitude: 46.603354,
    longitude: 1.888334,
    timezone: 'Europe/Paris',
    days: daysData,
  };
}

function demoPriceHistory(crop: Crop): { months: string[]; prices: number[] } {
  const series: Record<Crop, number[]> = {
    wheat: [326.08, 347.5, 387.67, 406.03, 444.16, 397.65, 321.98, 323.02, 346.32, 353.71, 344.33, 323.65, 320.1, 332.41, 309.43, 312.81, 299.44, 282.28, 278.62, 241.41, 229.39, 216.46, 216.0, 229.63, 226.08, 219.24, 211.84, 208.38, 227.43, 205.23, 183.23, 175.51, 188.51, 197.37, 185.73, 185.79, 190.63, 190.1, 179.61, 174.82, 196.84, 173.19, 165.27, 159.31, 155.12, 157.39, 169.2, 165.63, 169.25],
    maize: [276.72, 292.67, 335.93, 348.51, 344.91, 335.72, 312.68, 293.93, 312.55, 343.55, 320.93, 302.24, 302.84, 298.25, 284.96, 291.18, 268.17, 266.94, 235.27, 207.68, 223.85, 221.9, 209.04, 207.4, 198.76, 188.95, 190.23, 190.9, 201.02, 191.24, 177.77, 169.3, 183.66, 189.59, 201.31, 202.83, 214.36, 221.25, 207.75, 215.57, 204.81, 195.72, 192.45, 183.02, 196.15, 198.02, 201.66, 205.32, 203.9],
    grape: [780, 790, 805, 830, 855, 870, 865, 850, 840, 825, 815, 810, 800, 795, 785, 770, 755, 740, 730, 710, 695, 680, 670, 665, 660, 655, 650, 645, 648, 655, 660, 670, 685, 690, 695, 700, 705, 710, 715, 718, 720, 725, 722, 718, 712, 708, 705, 710, 715],
  };

  const data = series[crop];
  const months: string[] = [];
  let i = 0;
  for (let year = 2022; year <= 2026; year += 1) {
    for (let month = 1; month <= 12; month += 1) {
      if (i >= data.length) {
        break;
      }
      months.push(`${year}-${String(month).padStart(2, '0')}`);
      i += 1;
    }
  }

  return { months: months.slice(0, data.length), prices: data };
}

function demoYieldPrediction(crop: Crop): YieldPrediction {
  return {
    crop,
    country: 'France',
    predicted_yield_ton_ha: crop === 'wheat' ? 6.85 : crop === 'maize' ? 8.92 : 6.0,
    anomaly_percent: crop === 'wheat' ? -2.15 : crop === 'maize' ? -1.8 : -2.5,
    confidence: 0.75,
    explanation: 'Lower rainfall + NDVI anomaly -> likely lower yield (demo mode - backend not connected).',
  };
}

function demoPricePrediction(crop: Crop): PricePrediction {
  const prices: Record<Crop, [number, number]> = {
    wheat: [255, 268],
    maize: [212, 222],
    grape: [775, 790],
  };
  const [last, forecast] = prices[crop];

  return {
    crop,
    direction: 'Up',
    probability: 0.72,
    price_last_usd_mt: last,
    price_forecast_usd_mt: forecast,
    change_percent: Number((((forecast - last) / last) * 100).toFixed(1)),
    explanation: 'Lower yield forecast -> upward price pressure (demo mode - backend not connected).',
  };
}
