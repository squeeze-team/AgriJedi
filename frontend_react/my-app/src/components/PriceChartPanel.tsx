import { useEffect } from 'react';
import type { MultiPriceHistoryData } from '../services/api';
import { renderPriceChart } from './charts/renderPriceChart';
import { useContainerSize } from './charts/useContainerSize';

interface PriceChartPanelProps {
  data: MultiPriceHistoryData | null;
}

export function PriceChartPanel({ data }: PriceChartPanelProps) {
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

    renderPriceChart(node, data);
  }, [data, node, size.height, size.width]);

  return (
    <section className="panel-card">
      <div className="panel-title">Commodity Price History</div>
      <div className="h-[320px] p-3">
        {data ? <div ref={chartRef} className="h-full w-full" /> : <div className="loading-text">Loading price data...</div>}
      </div>
    </section>
  );
}
