import { useEffect, useRef } from 'react';
import { Chart, registerables } from 'chart.js';
import type { WeatherData } from '../services/api';

Chart.register(...registerables);

interface WeatherChartPanelProps {
  data: WeatherData | null;
}

export function WeatherChartPanel({ data }: WeatherChartPanelProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (!canvasRef.current || !data) {
      return;
    }

    const chart = new Chart(canvasRef.current, {
      type: 'bar',
      data: {
        labels: data.months,
        datasets: [
          {
            label: 'Precipitation (mm)',
            data: data.PRECTOTCORR,
            backgroundColor: 'rgba(37,99,235,0.5)',
            yAxisID: 'y',
            order: 2,
          },
          {
            label: 'Temp Mean (degC)',
            data: data.T2M,
            type: 'line',
            borderColor: '#ea580c',
            backgroundColor: 'rgba(234,88,12,0.1)',
            fill: true,
            tension: 0.3,
            yAxisID: 'y1',
            order: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: 'top' } },
        scales: {
          y: {
            position: 'left',
            title: { display: true, text: 'Precip (mm)' },
          },
          y1: {
            position: 'right',
            title: { display: true, text: 'Temp (degC)' },
            grid: { drawOnChartArea: false },
          },
        },
      },
    });

    return () => {
      chart.destroy();
    };
  }, [data]);

  return (
    <section className="panel-card">
      <div className="panel-title">Weather - Last 24 Months</div>
      <div className="h-[320px] p-3">
        {data ? <canvas ref={canvasRef} className="h-full w-full" /> : <div className="loading-text">Loading weather data...</div>}
      </div>
    </section>
  );
}
