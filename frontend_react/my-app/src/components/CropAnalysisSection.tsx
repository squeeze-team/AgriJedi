import type { CropAnalysisResponse } from '../services/api';

interface CropAnalysisSectionProps {
  data: CropAnalysisResponse | null;
  isLoading: boolean;
  error: string | null;
}

function getYieldBadgeClass(index: number | null) {
  if (index == null) {
    return 'bg-slate-100 text-slate-500';
  }
  if (index >= 1.02) {
    return 'bg-green-50 text-green-700';
  }
  if (index >= 0.98) {
    return 'bg-amber-50 text-amber-700';
  }
  return 'bg-red-50 text-red-700';
}

export function CropAnalysisSection({ data, isLoading, error }: CropAnalysisSectionProps) {
  const entries = data
    ? Object.entries(data.crops)
        .sort((a, b) => (b[1].area_pct || 0) - (a[1].area_pct || 0))
        .slice(0, 3)
    : [];

  return (
    <section className="mx-auto w-full max-w-[1400px] px-5 pb-7 md:px-7">
      <h2 className="mb-4 text-lg font-bold text-slate-800">Per-Crop NDVI Analysis & Yield Proxy</h2>

      {isLoading && <div className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500">Analysing crop distribution and NDVI...</div>}

      {!isLoading && error && <div className="rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-700">Analysis failed: {error}. Is the backend running?</div>}

      {!isLoading && !error && !data && (
        <div className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500">
          Load satellite imagery above to run per-crop analysis.
        </div>
      )}

      {!isLoading && !error && data && entries.length === 0 && (
        <div className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500">
          {data.error || 'No crop data found for this region.'}
        </div>
      )}

      {!isLoading && !error && data && entries.length > 0 && (
        <>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
            {entries.map(([group, item]) => {
              const yp = item.yield_prediction;
              const histValues = yp?.history ? Object.values(yp.history).join(' -> ') : '';
              const departments = yp?.departements?.join(', ') ?? '';
              const title = group.replace('_', ' ');

              return (
                <article key={group} className="panel-card p-4">
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <h3 className="text-sm font-bold text-slate-800">{title}</h3>
                    <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-semibold text-blue-700">
                      {item.area_pct}% area
                    </span>
                  </div>

                  <p className="mb-2 text-xs text-slate-500">{item.label}</p>

                  <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                    <dt className="text-slate-500">NDVI mean</dt>
                    <dd className="text-right font-semibold text-slate-800">{item.ndvi_mean}</dd>
                    <dt className="text-slate-500">NDVI median</dt>
                    <dd className="text-right font-semibold text-slate-800">{item.ndvi_median}</dd>
                    <dt className="text-slate-500">NDVI s</dt>
                    <dd className="text-right font-semibold text-slate-800">{item.ndvi_std}</dd>
                    <dt className="text-slate-500">NDVI IQR</dt>
                    <dd className="text-right font-semibold text-slate-800">
                      {item.ndvi_p25} - {item.ndvi_p75}
                    </dd>
                    <dt className="text-slate-500">Pixels</dt>
                    <dd className="text-right font-semibold text-slate-800">{item.pixel_count.toLocaleString()}</dd>
                  </dl>

                  <div className="mt-2">
                    <span className={`inline-block rounded-full px-2 py-1 text-xs font-semibold ${getYieldBadgeClass(item.yield_index)}`}>
                      NDVI index: {item.yield_index != null ? item.yield_index.toFixed(2) : 'N/A'} - {item.yield_index_label || 'N/A'}
                    </span>
                  </div>

                  {yp && (
                    <div className="mt-3 rounded-md border-l-4 border-blue-600 bg-slate-50 p-3">
                      <div className="text-xs font-semibold text-slate-800">{yp.target_year} Yield Forecast</div>
                      <div className="mt-1 text-2xl font-extrabold text-blue-700">
                        {yp.predicted_yield_t_ha} t/ha
                        <span className={`ml-2 text-xs font-semibold ${yp.anomaly_vs_5yr_pct >= 0 ? 'text-green-700' : 'text-red-700'}`}>
                          {yp.anomaly_vs_5yr_pct >= 0 ? '+' : ''}
                          {yp.anomaly_vs_5yr_pct}% vs 5yr avg
                        </span>
                      </div>
                      <div className="mt-1 text-[11px] text-slate-500">
                        5yr avg: {yp.avg_5yr} t/ha | Trend: {yp.trend >= 0 ? '+' : ''}
                        {yp.trend} t/ha/yr
                      </div>
                      {histValues && <div className="mt-1 text-[11px] text-slate-500">History: {histValues} t/ha</div>}
                      <div className="mt-1 text-[11px] text-slate-500">
                        {departments ? `Departements: ${departments} | ` : ''}
                        Confidence: {(yp.confidence * 100).toFixed(0)}%
                      </div>
                    </div>
                  )}
                </article>
              );
            })}
          </div>

          <div className="pt-2 text-xs text-slate-500">
            Region: [{data.bbox}] - {data.total_classified_pixels.toLocaleString()} classified pixels at {data.resolution_px} - Source:{' '}
            {data.item_id || 'bundled'}
          </div>
        </>
      )}
    </section>
  );
}
