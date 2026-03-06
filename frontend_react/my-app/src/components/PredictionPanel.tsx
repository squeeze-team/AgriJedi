import type { PricePrediction, YieldPrediction } from '../services/api';

interface PredictionPanelProps {
  yieldResult: YieldPrediction | null;
  priceResult: PricePrediction | null;
  isYieldLoading: boolean;
  isPriceLoading: boolean;
}

export function PredictionPanel({
  yieldResult,
  priceResult,
  isYieldLoading,
  isPriceLoading,
}: PredictionPanelProps) {
  const yieldPositive = (yieldResult?.anomaly_percent ?? 0) >= 0;

  const badgeClass =
    priceResult?.direction === 'Up'
      ? 'badge-up'
      : priceResult?.direction === 'Down'
        ? 'badge-down'
        : 'badge-flat';

  const arrow =
    priceResult?.direction === 'Up'
      ? '↑'
      : priceResult?.direction === 'Down'
        ? '↓'
        : '→';

  return (
    <section className="panel-card lg:col-span-2">
      <div className="grid grid-cols-1 lg:grid-cols-2">
        <div className="p-5 lg:p-6">
          <h3 className="mb-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">Yield Prediction</h3>

          {isYieldLoading && <div className="loading-text">Running yield prediction...</div>}

          {!isYieldLoading && !yieldResult && <div className="loading-text">Select crop and click Run Prediction.</div>}

          {!isYieldLoading && yieldResult && (
            <>
              <div className={`text-3xl font-bold ${yieldPositive ? 'text-green-600' : 'text-red-600'}`}>
                {yieldResult.predicted_yield_ton_ha} t/ha
              </div>
              <div className="mt-2 text-sm text-slate-600">
                Anomaly:{' '}
                <strong className={yieldPositive ? 'text-green-600' : 'text-red-600'}>
                  {yieldResult.anomaly_percent >= 0 ? '+' : ''}
                  {yieldResult.anomaly_percent}%
                </strong>
                {' | '}Confidence: {(yieldResult.confidence * 100).toFixed(0)}%
              </div>
              <div className="mt-3 rounded-md border-l-4 border-blue-600 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                {yieldResult.explanation}
              </div>
            </>
          )}
        </div>

        <div className="border-t border-slate-200 p-5 lg:border-t-0 lg:border-l lg:p-6">
          <h3 className="mb-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">Price Forecast (3-month)</h3>

          {isPriceLoading && <div className="loading-text">Running price prediction...</div>}

          {!isPriceLoading && !priceResult && <div className="loading-text">Waiting for prediction...</div>}

          {!isPriceLoading && priceResult && (
            <>
              <div className="flex flex-wrap items-center gap-3">
                <span className={`badge ${badgeClass}`}>
                  {arrow} {priceResult.direction}
                </span>
                <span className="text-base font-semibold text-slate-700">
                  {(priceResult.probability * 100).toFixed(0)}% confidence
                </span>
              </div>
              <div className="mt-2 text-sm text-slate-600">
                Last: ${priceResult.price_last_usd_mt}/mt - Forecast: ${priceResult.price_forecast_usd_mt}/mt ({' '}
                {priceResult.change_percent >= 0 ? '+' : ''}
                {priceResult.change_percent}%)
              </div>
              <div className="mt-3 rounded-md border-l-4 border-blue-600 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                {priceResult.explanation}
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
