export const API_BASE = 'http://localhost:8000';

export type Crop = 'wheat' | 'maize' | 'grape';
export type PriceDirection = 'Up' | 'Down' | 'Flat';
export type SatelliteLayer = 'rgb' | 'false_color' | 'ndvi' | 'overlay';

export interface WeatherData {
  months: string[];
  PRECTOTCORR: number[];
  T2M: number[];
}

export interface PriceHistoryData {
  months: string[];
  prices: number[];
  unit: string;
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
    const response = await fetch(`${API_BASE}/weather/france?start=${start}&end=${end}`);
    const data = (await response.json()) as Partial<WeatherData>;
    if (data.months && data.months.length > 0 && data.PRECTOTCORR && data.T2M) {
      return data as WeatherData;
    }
    return demoWeatherData();
  } catch {
    return demoWeatherData();
  }
}

export async function fetchPriceHistory(crop: Crop): Promise<PriceHistoryData> {
  try {
    const response = await fetch(`${API_BASE}/prices/history?crop=${crop}`);
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

export async function fetchYieldPrediction(crop: Crop): Promise<YieldPrediction> {
  try {
    const response = await fetch(`${API_BASE}/predict/yield?crop=${crop}&country=France`);
    return (await response.json()) as YieldPrediction;
  } catch {
    return demoYieldPrediction(crop);
  }
}

export async function fetchPricePrediction(crop: Crop): Promise<PricePrediction> {
  try {
    const response = await fetch(`${API_BASE}/predict/price?crop=${crop}`);
    return (await response.json()) as PricePrediction;
  } catch {
    return demoPricePrediction(crop);
  }
}

export async function fetchCropAnalysis(bbox: string, date: string): Promise<CropAnalysisResponse> {
  const response = await fetch(
    `${API_BASE}/analysis/crop-ndvi?bbox=${encodeURIComponent(bbox)}&date=${encodeURIComponent(date)}&resolution=400`,
  );
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return (await response.json()) as CropAnalysisResponse;
}

export function buildSatelliteUrl(bbox: string, date: string, layer: SatelliteLayer) {
  return `${API_BASE}/satellite/view?bbox=${encodeURIComponent(bbox)}&date=${encodeURIComponent(date)}&layer=${layer}&width=600&height=600`;
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
