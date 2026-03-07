import { useEffect, useMemo, useState } from 'react';
import { Header } from './components/Header';
import { MapPanel } from './components/MapPanel';
import { PriceChartPanel } from './components/PriceChartPanel';
import { CropAnalysisSection } from './components/CropAnalysisSection';
import { ChatBubble } from './components/ChatBubble';
import type { CropLegendItem } from './components/CropLegend';
import { RiskAnalysisPanel } from './components/RiskAnalysisPanel';
import { SatelliteSection } from './components/SatelliteSection';
import { WeatherChartPanel } from './components/WeatherChartPanel';
import {
  fetchSatelliteLayerImage,
  fetchAllPriceHistory,
  fetchCropAnalysis,
  fetchWeather,
  type CropAnalysisResponse,
  type MultiPriceHistoryData,
  type SatelliteLayer,
  type WeatherData,
} from './services/api';

interface SatelliteViewState {
  src: string | null;
  status: 'idle' | 'loading' | 'loaded' | 'error';
}

const satelliteLayers: Array<Exclude<SatelliteLayer, 'false_color'>> = ['rgb', 'ndvi', 'overlay'];

const defaultBbox = '4.67,44.71,4.97,45.01';
const defaultDate = '2025-06-01/2025-09-01';
let hasTriggeredInitialLoad = false;

const groupLegendColor: Record<string, string> = {
  maize: '#f4de7a',
  wheat: '#d8b47f',
  grape: '#e7a5c8',
  grassland: '#9fd48a',
  other_cereal: '#c9a25f',
  other_fruit: '#bf88d8',
  other: '#e7b58b',
};

function formatGroupLabel(group: string) {
  return group
    .split('_')
    .map((token) => token.charAt(0).toUpperCase() + token.slice(1))
    .join(' ');
}

function createInitialSatelliteViews(): Record<SatelliteLayer, SatelliteViewState> {
  return {
    rgb: { src: null, status: 'idle' },
    false_color: { src: null, status: 'idle' },
    ndvi: { src: null, status: 'idle' },
    overlay: { src: null, status: 'idle' },
  };
}

function App() {
  const [weatherData, setWeatherData] = useState<WeatherData | null>(null);
  const [priceData, setPriceData] = useState<MultiPriceHistoryData | null>(null);

  const [bbox, setBbox] = useState(defaultBbox);
  const [satDate, setSatDate] = useState(defaultDate);
  const [mapBbox, setMapBbox] = useState(defaultBbox);
  const [analysisData, setAnalysisData] = useState<CropAnalysisResponse | null>(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [analysisAutoRunSignal, setAnalysisAutoRunSignal] = useState(0);
  const [satelliteViews, setSatelliteViews] = useState<Record<SatelliteLayer, SatelliteViewState>>(
    createInitialSatelliteViews(),
  );
  const dynamicLegendItems = useMemo<CropLegendItem[] | undefined>(() => {
    if (!analysisData) {
      return undefined;
    }
    const topThree = Object.entries(analysisData.crops)
      .sort((a, b) => (b[1].area_pct || 0) - (a[1].area_pct || 0))
      .slice(0, 3);

    if (topThree.length === 0) {
      return undefined;
    }

    return topThree.map(([group]) => ({
      label: formatGroupLabel(group),
      color: groupLegendColor[group] ?? '#94a3b8',
    }));
  }, [analysisData]);

  useEffect(() => {
    fetchWeather().then(setWeatherData);
  }, []);

  useEffect(() => {
    fetchAllPriceHistory().then(setPriceData);
  }, []);

  async function loadSatelliteViewsBy(nextBbox: string, nextDate: string) {
    setBbox(nextBbox);
    setSatDate(nextDate);
    setMapBbox(nextBbox);

    setSatelliteViews((previous) => {
      const next = { ...previous };
      satelliteLayers.forEach((layer) => {
        next[layer] = { ...previous[layer], status: 'loading' };
      });
      return next;
    });

    setAnalysisLoading(true);
    setAnalysisError(null);
    try {
      const result = await fetchCropAnalysis(nextBbox, nextDate);
      setAnalysisData(result);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      setAnalysisError(message);
      setAnalysisData(null);
    } finally {
      setAnalysisLoading(false);
    }

    await Promise.all(
      satelliteLayers.map(async (layer) => {
        try {
          const objectUrl = await fetchSatelliteLayerImage(nextBbox, nextDate, layer);
          setSatelliteViews((previous) => {
            const prevSrc = previous[layer].src;
            if (prevSrc && prevSrc.startsWith('blob:')) {
              URL.revokeObjectURL(prevSrc);
            }
            return {
              ...previous,
              [layer]: {
                src: objectUrl,
                status: 'loading',
              },
            };
          });
        } catch {
          setSatelliteViews((previous) => ({
            ...previous,
            [layer]: {
              ...previous[layer],
              status: 'error',
            },
          }));
        }
      }),
    );
  }

  async function loadSatelliteViews() {
    await loadSatelliteViewsBy(bbox, satDate);
  }

  useEffect(() => {
    if (hasTriggeredInitialLoad) {
      return;
    }
    hasTriggeredInitialLoad = true;
    void loadSatelliteViewsBy(defaultBbox, defaultDate);
  }, []);

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
    <div className="dashboard-shell min-h-screen text-slate-100">
      <Header />

      <main className="mx-auto grid w-full max-w-[1400px] grid-cols-1 gap-4 px-5 py-5 md:px-7 lg:grid-cols-2">
        <MapPanel bbox={mapBbox} legendItems={dynamicLegendItems} />
        <WeatherChartPanel data={weatherData} />
        <PriceChartPanel data={priceData} />
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
        legendItems={dynamicLegendItems}
      />

      <CropAnalysisSection data={analysisData} isLoading={analysisLoading} error={analysisError} />
      <RiskAnalysisPanel bbox={bbox} autoRunSignal={analysisAutoRunSignal} />
      <ChatBubble
        onAutofillSatellite={({ bbox: nextBbox, dateRange }) => {
          void (async () => {
            await loadSatelliteViewsBy(nextBbox, dateRange);
            setAnalysisAutoRunSignal((previous) => previous + 1);
          })();
        }}
      />
    </div>
  );
}

export default App;
