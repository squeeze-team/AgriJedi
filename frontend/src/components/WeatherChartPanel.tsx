import { useEffect } from 'react';
import type { WeatherData, WeatherForecastData } from '../services/api';
import { renderWeatherChart } from './charts/renderWeatherChart';
import { useContainerSize } from './charts/useContainerSize';

interface WeatherChartPanelProps {
  data: WeatherData | null;
  forecast: WeatherForecastData | null;
}

function toWeekday(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString('en-US', { weekday: 'short' });
}

function weatherGlyph(code: number | null) {
  if (code == null) return '•';
  if (code === 0) return '☀';
  if (code === 1 || code === 2) return '⛅';
  if (code === 3) return '☁';
  if (code >= 45 && code <= 48) return '🌫';
  if ((code >= 51 && code <= 67) || (code >= 80 && code <= 82)) return '🌧';
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return '❄';
  if (code >= 95) return '⛈';
  return '🌦';
}

export function WeatherChartPanel({ data, forecast }: WeatherChartPanelProps) {
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
      <div className="h-[320px] p-3 pb-2">
        {data ? <div ref={chartRef} className="h-full w-full" /> : <div className="loading-text">Loading weather data...</div>}
      </div>
      <div className="px-3 pb-3">
        <div className="mb-2 text-[11px] uppercase tracking-[0.18em] text-cyan-300/85">Next 7 Days</div>
        {forecast ? (
          <div className="grid grid-cols-7 gap-1.5">
            {forecast.days.slice(0, 7).map((day) => (
              <article
                key={day.date}
                className="rounded-xl border border-cyan-400/25 bg-[linear-gradient(180deg,rgba(15,23,42,0.65),rgba(15,23,42,0.35))] px-2 py-2 text-center"
              >
                <div className="text-[10px] font-semibold tracking-wide text-slate-300">{toWeekday(day.date)}</div>
                <div className="mt-1 text-lg leading-none">{weatherGlyph(day.weather_code)}</div>
                <div className="mt-1 text-[11px] font-semibold text-slate-100">
                  {day.temp_max_c != null ? `${Math.round(day.temp_max_c)}°` : '--'}
                  <span className="ml-1 text-slate-400">
                    {day.temp_min_c != null ? `${Math.round(day.temp_min_c)}°` : '--'}
                  </span>
                </div>
                <div className="mt-1 text-[10px] text-cyan-200/90">
                  {day.precip_mm != null ? `${day.precip_mm}mm` : '--'}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="cyber-note px-3 py-2 text-sm text-slate-300">Loading 7-day forecast...</div>
        )}
      </div>
    </section>
  );
}
