import { useEffect } from 'react';
import type { WeatherData } from '../services/api';
import { renderWeatherChart } from './charts/renderWeatherChart';
import { useContainerSize } from './charts/useContainerSize';

interface WeatherChartPanelProps {
  data: WeatherData | null;
}

export function WeatherChartPanel({ data }: WeatherChartPanelProps) {
  const { ref: chartRef, size, node } = useContainerSize<HTMLDivElement>();

  useEffect(() => {
    if (!node) {
      return;
    }

    if (!data) {
      node.replaceChildren();
      return;
    }

    if (size.width === 0 || size.height === 0) {
      return;
    }

    renderWeatherChart(node, data);
  }, [data, node, size.height, size.width]);

  return (
    <section className="panel-card">
      <div className="panel-title">Weather - Last 24 Months</div>
      <div className="h-[320px] p-3">
        {data ? <div ref={chartRef} className="h-full w-full" /> : <div className="loading-text">Loading weather data...</div>}
      </div>
    </section>
  );
}
