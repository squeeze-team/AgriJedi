import { useEffect, useRef } from 'react';
import { Chart, registerables } from 'chart.js';
import type { Crop, PriceHistoryData } from '../services/api';
import { getCropLabel } from '../services/api';

Chart.register(...registerables);

interface PriceChartPanelProps {
  crop: Crop;
  data: PriceHistoryData | null;
}

export function PriceChartPanel({ crop, data }: PriceChartPanelProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (!canvasRef.current || !data) {
      return;
    }

    const chart = new Chart(canvasRef.current, {
      type: 'line',
      data: {
        labels: data.months,
        datasets: [
          {
            label: `${getCropLabel(crop)} Price (${data.unit})${data.isDemo ? ' - demo' : ''}`,
            data: data.prices,
            borderColor: '#16a34a',
            backgroundColor: 'rgba(22,163,74,0.08)',
            fill: true,
            tension: 0.3,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: 'top' } },
        scales: { y: { title: { display: true, text: 'USD / metric ton' } } },
      },
    });

    return () => {
      chart.destroy();
    };
  }, [crop, data]);

  return (
    <section className="panel-card">
      <div className="panel-title">Commodity Price History</div>
      <div className="h-[320px] p-3">
        {data ? <canvas ref={canvasRef} className="h-full w-full" /> : <div className="loading-text">Loading price data...</div>}
      </div>
    </section>
  );
}
