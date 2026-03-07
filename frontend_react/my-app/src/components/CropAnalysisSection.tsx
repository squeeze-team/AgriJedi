import type { CropAnalysisResponse } from '../services/api';

interface CropAnalysisSectionProps {
  data: CropAnalysisResponse | null;
  isLoading: boolean;
  error: string | null;
}

function getYieldBadgeClass(index: number | null) {
  if (index == null) {
    return 'bg-slate-700/40 text-slate-300';
  }
  if (index >= 1.02) {
    return 'bg-emerald-400/15 text-emerald-300';
  }
  if (index >= 0.98) {
    return 'bg-amber-300/15 text-amber-200';
  }
  return 'bg-rose-400/15 text-rose-300';
}

export function CropAnalysisSection({ data, isLoading, error }: CropAnalysisSectionProps) {
  const entries = data
    ? Object.entries(data.crops)
        .sort((a, b) => (b[1].area_pct || 0) - (a[1].area_pct || 0))
        .slice(0, 3)
    : [];

  return (
    <section className="mx-auto w-full max-w-[1400px] px-5 pb-7 md:px-7">
      <h2 className="mb-4 text-lg font-bold tracking-[0.06em] text-slate-100">Crop Health & Yield Outlook</h2>

      {isLoading && <div className="cyber-note p-5 text-sm text-slate-300">Analysing crop distribution and NDVI...</div>}

      {!isLoading && error && <div className="rounded-xl border border-rose-500/40 bg-rose-950/40 p-5 text-sm text-rose-200">Analysis failed: {error}. Is the backend running?</div>}

      {!isLoading && !error && !data && (
        <div className="cyber-note p-5 text-sm text-slate-300">
          Load satellite imagery above to run per-crop analysis.
        </div>
      )}

      {!isLoading && !error && data && entries.length === 0 && (
        <div className="cyber-note p-5 text-sm text-slate-300">
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
                    <h3 className="text-sm font-bold uppercase tracking-[0.08em] text-slate-100">{title}</h3>
                    <span className="rounded-full bg-cyan-400/15 px-2 py-0.5 text-xs font-semibold text-cyan-200">
                      {item.area_pct}% area
                    </span>
                  </div>

                  <p className="mb-2 text-xs text-slate-400">{item.label}</p>

                  <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                    <dt className="text-slate-400">NDVI mean</dt>
                    <dd className="text-right font-semibold text-slate-100">{item.ndvi_mean}</dd>
                    <dt className="text-slate-400">NDVI median</dt>
                    <dd className="text-right font-semibold text-slate-100">{item.ndvi_median}</dd>
                    <dt className="text-slate-400">NDVI s</dt>
                    <dd className="text-right font-semibold text-slate-100">{item.ndvi_std}</dd>
                    <dt className="text-slate-400">NDVI IQR</dt>
                    <dd className="text-right font-semibold text-slate-100">
                      {item.ndvi_p25} - {item.ndvi_p75}
                    </dd>
                    <dt className="text-slate-400">Pixels</dt>
                    <dd className="text-right font-semibold text-slate-100">{item.pixel_count.toLocaleString()}</dd>
                  </dl>

                  <div className="mt-2">
                    <span className={`inline-block rounded-full px-2 py-1 text-xs font-semibold ${getYieldBadgeClass(item.yield_index)}`}>
                      NDVI index: {item.yield_index != null ? item.yield_index.toFixed(2) : 'N/A'} - {item.yield_index_label || 'N/A'}
                    </span>
                  </div>

                  {yp && (
                    <div className="mt-3 rounded-md border border-slate-700 bg-slate-950/70 p-3">
                      <div className="text-xs font-semibold text-slate-200">{yp.target_year} Yield Forecast</div>
                      <div className="mt-1 text-2xl font-extrabold text-cyan-300">
                        {yp.predicted_yield_t_ha} t/ha
                        <span className={`ml-2 text-xs font-semibold ${yp.anomaly_vs_5yr_pct >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>
                          {yp.anomaly_vs_5yr_pct >= 0 ? '+' : ''}
                          {yp.anomaly_vs_5yr_pct}% vs 5yr avg
                        </span>
                      </div>
                      <div className="mt-1 text-[11px] text-slate-400">
                        5yr avg: {yp.avg_5yr} t/ha | Trend: {yp.trend >= 0 ? '+' : ''}
                        {yp.trend} t/ha/yr
                      </div>
                      {histValues && <div className="mt-1 text-[11px] text-slate-400">History: {histValues} t/ha</div>}
                      <div className="mt-1 text-[11px] text-slate-400">
                        {departments ? `Departements: ${departments} | ` : ''}
                        Confidence: {(yp.confidence * 100).toFixed(0)}%
                      </div>
                    </div>
                  )}
                </article>
              );
            })}
          </div>

          <div className="pt-2 text-xs text-slate-400">
            Region: [{data.bbox}] - {data.total_classified_pixels.toLocaleString()} classified pixels at {data.resolution_px} - Source:{' '}
            {data.item_id || 'bundled'}
          </div>
        </>
      )}
    </section>
  );
}
