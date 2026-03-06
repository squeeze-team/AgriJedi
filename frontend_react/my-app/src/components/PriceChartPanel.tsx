import { useEffect, useRef } from 'react';
import { Chart, registerables } from 'chart.js';
import type { MultiPriceHistoryData } from '../services/api';

Chart.register(...registerables);

interface PriceChartPanelProps {
  data: MultiPriceHistoryData | null;
}

const seriesStyles = [
  { key: 'wheat', label: 'Wheat Price', color: '#16a34a' },
  { key: 'maize', label: 'Maize Price', color: '#2563eb' },
  { key: 'grape', label: 'Grape Price', color: '#9333ea' },
] as const;

export function PriceChartPanel({ data }: PriceChartPanelProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (!canvasRef.current || !data) {
      return;
    }

    const chart = new Chart(canvasRef.current, {
      type: 'line',
      data: {
        labels: data.months,
        datasets: seriesStyles.map((series) => ({
          label: `${series.label} (${data.unit})${data.isDemo ? ' - demo' : ''}`,
          data: data.series[series.key],
          borderColor: series.color,
          backgroundColor: 'transparent',
          fill: false,
          pointRadius: 1.8,
          pointHoverRadius: 3,
          borderWidth: 2,
          tension: 0.3,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: 'top' } },
        scales: { y: { title: { display: true, text: 'USD / metric ton' } } },
        interaction: {
          mode: 'index',
          intersect: false,
        },
      },
    });

    return () => {
      chart.destroy();
    };
  }, [data]);

  return (
    <section className="panel-card">
      <div className="panel-title">Commodity Price History</div>
      <div className="h-[320px] p-3">
        {data ? <canvas ref={canvasRef} className="h-full w-full" /> : <div className="loading-text">Loading price data...</div>}
      </div>
    </section>
  );
}
