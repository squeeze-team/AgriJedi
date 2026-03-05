import { useEffect, useState } from 'react';
import { Header } from './components/Header';
import { MapPanel } from './components/MapPanel';
import { PredictionPanel } from './components/PredictionPanel';
import { PriceChartPanel } from './components/PriceChartPanel';
import { CropAnalysisSection } from './components/CropAnalysisSection';
import { ChatBubble } from './components/ChatBubble';
import { SatelliteSection } from './components/SatelliteSection';
import { WeatherChartPanel } from './components/WeatherChartPanel';
import {
  buildSatelliteUrl,
  fetchCropAnalysis,
  fetchPriceHistory,
  fetchPricePrediction,
  fetchWeather,
  fetchYieldPrediction,
  type CropAnalysisResponse,
  type Crop,
  type PriceHistoryData,
  type PricePrediction,
  type SatelliteLayer,
  type WeatherData,
  type YieldPrediction,
} from './services/api';

interface SatelliteViewState {
  src: string | null;
  status: 'idle' | 'loading' | 'loaded' | 'error';
}

const satelliteLayers: SatelliteLayer[] = ['rgb', 'false_color', 'ndvi', 'overlay'];

const defaultBbox = '4.67,44.71,4.97,45.01';
const defaultDate = '2025-06-01/2025-09-01';

function createInitialSatelliteViews(): Record<SatelliteLayer, SatelliteViewState> {
  return {
    rgb: { src: null, status: 'idle' },
    false_color: { src: null, status: 'idle' },
    ndvi: { src: null, status: 'idle' },
    overlay: { src: null, status: 'idle' },
  };
}

function App() {
  const [crop, setCrop] = useState<Crop>('wheat');

  const [weatherData, setWeatherData] = useState<WeatherData | null>(null);
  const [priceData, setPriceData] = useState<PriceHistoryData | null>(null);

  const [yieldResult, setYieldResult] = useState<YieldPrediction | null>(null);
  const [priceResult, setPriceResult] = useState<PricePrediction | null>(null);
  const [isYieldLoading, setIsYieldLoading] = useState(false);
  const [isPriceLoading, setIsPriceLoading] = useState(false);

  const [bbox, setBbox] = useState(defaultBbox);
  const [satDate, setSatDate] = useState(defaultDate);
  const [mapBbox, setMapBbox] = useState(defaultBbox);
  const [analysisData, setAnalysisData] = useState<CropAnalysisResponse | null>(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [satelliteViews, setSatelliteViews] = useState<Record<SatelliteLayer, SatelliteViewState>>(
    createInitialSatelliteViews(),
  );

  useEffect(() => {
    fetchWeather().then(setWeatherData);
  }, []);

  useEffect(() => {
    setPriceData(null);
    fetchPriceHistory(crop).then(setPriceData);
  }, [crop]);

  async function runPredictions() {
    setIsYieldLoading(true);
    setIsPriceLoading(true);
    setYieldResult(null);
    setPriceResult(null);

    const [yieldPrediction, pricePrediction] = await Promise.all([
      fetchYieldPrediction(crop),
      fetchPricePrediction(crop),
    ]);

    setYieldResult(yieldPrediction);
    setPriceResult(pricePrediction);
    setIsYieldLoading(false);
    setIsPriceLoading(false);
  }

  async function loadSatelliteViews() {
    setMapBbox(bbox);

    setSatelliteViews((previous) => {
      const next = { ...previous };
      satelliteLayers.forEach((layer) => {
        next[layer] = {
          src: buildSatelliteUrl(bbox, satDate, layer),
          status: 'loading',
        };
      });
      return next;
    });

    setAnalysisLoading(true);
    setAnalysisError(null);
    try {
      const result = await fetchCropAnalysis(bbox, satDate);
      setAnalysisData(result);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      setAnalysisError(message);
      setAnalysisData(null);
    } finally {
      setAnalysisLoading(false);
    }
  }

  function setLayerStatus(layer: SatelliteLayer, status: SatelliteViewState['status']) {
    setSatelliteViews((previous) => ({
      ...previous,
      [layer]: {
        ...previous[layer],
        status,
      },
    }));
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800">
      <Header crop={crop} onCropChange={setCrop} onRunPrediction={runPredictions} />

      <main className="mx-auto grid w-full max-w-[1400px] grid-cols-1 gap-4 px-5 py-5 md:px-7 lg:grid-cols-2">
        <MapPanel bbox={mapBbox} />
        <WeatherChartPanel data={weatherData} />
        <PriceChartPanel crop={crop} data={priceData} />
        <PredictionPanel
          yieldResult={yieldResult}
          priceResult={priceResult}
          isYieldLoading={isYieldLoading}
          isPriceLoading={isPriceLoading}
        />
      </main>

      <SatelliteSection
        bbox={bbox}
        date={satDate}
        views={satelliteViews}
        onBboxChange={setBbox}
        onDateChange={setSatDate}
        onLoad={loadSatelliteViews}
        onImageLoad={(layer) => setLayerStatus(layer, 'loaded')}
        onImageError={(layer) => setLayerStatus(layer, 'error')}
      />

      <CropAnalysisSection data={analysisData} isLoading={analysisLoading} error={analysisError} />
      <ChatBubble />
    </div>
  );
}

export default App;
