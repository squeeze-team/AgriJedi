import { useState } from 'react';
import { fetchAnalysisReport, type AnalysisReport } from '../services/api';

/* ── colour helpers (1-5 scale) ───────────────────── */

function scoreColor(score: number) {
  if (score <= 1) return { text: 'text-emerald-300', bg: 'bg-emerald-400', ring: 'ring-emerald-400/35', badge: 'bg-emerald-400/15 text-emerald-300' };
  if (score <= 2) return { text: 'text-green-300', bg: 'bg-green-400', ring: 'ring-green-400/35', badge: 'bg-green-400/15 text-green-300' };
  if (score <= 3) return { text: 'text-amber-300', bg: 'bg-amber-400', ring: 'ring-amber-400/35', badge: 'bg-amber-400/15 text-amber-200' };
  if (score <= 4) return { text: 'text-orange-300', bg: 'bg-orange-400', ring: 'ring-orange-400/35', badge: 'bg-orange-400/15 text-orange-200' };
  return { text: 'text-rose-300', bg: 'bg-rose-400', ring: 'ring-rose-400/35', badge: 'bg-rose-400/15 text-rose-200' };
}

function riskLabel(score: number) {
  if (score <= 1) return 'Very Low';
  if (score <= 2) return 'Low';
  if (score <= 3) return 'Moderate';
  if (score <= 4) return 'High';
  return 'Critical';
}

const RISK_ICON: Record<string, string> = {
  'Very Low': '🟢',
  Low: '🟢',
  Moderate: '🟡',
  High: '🟠',
  Critical: '🔴',
};

const ACTION_STYLE: Record<string, string> = {
  sell: 'bg-rose-400/15 text-rose-200 border-rose-400/40',
  hold: 'bg-amber-300/15 text-amber-200 border-amber-300/40',
};

const MARKET_KEY = 'Market & Weather Risk Assessment';

/** Human-readable labels for market/weather sub-keys */
const MARKET_LABELS: Record<string, string> = {
  market_focus_crop: 'Focus Crop',
  latest_price: 'Latest Price',
  trend_direction: 'Trend',
  period_change_pct: 'Period Change %',
  weather_risk_score: 'Weather Risk',
  soil_moisture_pct: 'Soil Moisture %',
  precipitation_mm: 'Precipitation (mm)',
  heat_risk: 'Heat Risk',
  flood_risk: 'Flood Risk',
};

function formatMarketValue(key: string, val: string | number | undefined): string {
  if (val == null) return '—';
  if (typeof val === 'number') {
    if (key.includes('pct') || key.includes('risk') || key === 'weather_risk_score')
      return val.toFixed(2);
    if (key === 'latest_price') return `€${val.toFixed(1)}`;
    return val.toFixed(1);
  }
  return String(val);
}

function trendBadge(dir: string) {
  if (dir === 'rising') return 'text-emerald-300 bg-emerald-500/15';
  if (dir === 'falling') return 'text-rose-300 bg-rose-500/15';
  return 'text-slate-300 bg-slate-700/40';
}

function riskBadge(val: number) {
  if (val <= 0.3) return 'text-emerald-300';
  if (val <= 0.6) return 'text-amber-300';
  return 'text-rose-300';
}

/** Keys rendered in the left summary panel — skip in right detail grid. */
const LEFT_KEYS = new Set([
  'risk_score',
  'crop_type',
  'crop_type_in_bbox',
  'selected_bbox',
  'recommended_action',
]);

/** Ordered keys for the right detail cards. */
const DETAIL_KEY_ORDER = [
  'Geospatial & Crop Context',
  'Yield & Vegetation Assessment',
  'Market & Weather Risk Assessment',
  'Bio-monitor Interpretation',
  'Risk Triggers to Watch (next planning horizon)',
];

/* ── component ─────────────────────────────────────── */

interface RiskAnalysisPanelProps {
  bbox?: string;
}

export function RiskAnalysisPanel({ bbox = '' }: RiskAnalysisPanelProps) {
  const [report, setReport] = useState<AnalysisReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runAnalysis() {
    setLoading(true);
    setError(null);
    try {
      const next = await fetchAnalysisReport(bbox);
      setReport(next);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown analysis error';
      setError(message);
      setReport(null);
    } finally {
      setLoading(false);
    }
  }

  const score = report?.risk_score ?? 0;
  const level = report ? riskLabel(score) : null;
  const palette = scoreColor(score);

  /* Build ordered detail entries for right side (skip market key – rendered separately). */
  const detailEntries: [string, string][] = report
    ? DETAIL_KEY_ORDER
        .filter((key) => key in report && key !== MARKET_KEY)
        .map((key) => [key, String(report[key] ?? '—')])
    : [];

  /* Market data object (if present). */
  const marketData = report?.[MARKET_KEY] as Record<string, string | number | undefined> | undefined;

  /* Any remaining keys not in LEFT_KEYS or DETAIL_KEY_ORDER */
  const extraEntries: [string, string][] = report
    ? Object.entries(report)
        .filter(([key]) => !LEFT_KEYS.has(key) && !DETAIL_KEY_ORDER.includes(key))
        .map(([key, val]) => {
          if (typeof val === 'boolean') return [key, val ? 'Yes' : 'No'];
          if (Array.isArray(val)) return [key, val.join(', ')];
          return [key, String(val ?? '—')];
        })
    : [];

  const allDetails = [...detailEntries, ...extraEntries];

  return (
    <section className="mx-auto w-full max-w-[1400px] px-5 pb-7 md:px-7">
      {/* Header row */}
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-bold tracking-[0.06em] text-slate-100">⚠️ AI Risk Analysis</h2>
        <button
          onClick={runAnalysis}
          disabled={loading}
          className="cyber-action flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-semibold text-cyan-100 transition disabled:opacity-60"
        >
          {loading ? (
            <>
              <span className="animate-spin">⏳</span> Analysing…
            </>
          ) : (
            <>⚡ Run Analysis</>
          )}
        </button>
      </div>

      {/* Empty state */}
      {!report && !loading && (
        <div className="cyber-note p-5 text-sm text-slate-300">
          Click <strong>"Run Analysis"</strong> to generate an AI-powered risk report for the selected region.
          <span className="ml-1 text-xs text-slate-400">(bbox: {bbox || 'none'})</span>
        </div>
      )}

      {error && (
        <div className="mb-3 rounded-lg border border-rose-400/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-200">
          Analysis failed: {error}
        </div>
      )}

      {/* Loading skeleton */}
      {loading && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_1fr]">
          <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-cyan-400/25 bg-slate-950/75 p-8">
            <div className="h-28 w-28 animate-pulse rounded-full bg-slate-800/80" />
            <div className="h-4 w-32 animate-pulse rounded bg-slate-800/80" />
            <div className="h-4 w-24 animate-pulse rounded bg-slate-800/80" />
          </div>
          <div className="space-y-3">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-24 animate-pulse rounded-xl border border-cyan-400/20 bg-slate-950/75" />
            ))}
          </div>
        </div>
      )}

      {/* ── Main grid ───────────────────────────────── */}
      {report && !loading && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_1fr]">
          {/* ─── Left: Score + meta ─── */}
          <div className="flex flex-col items-center gap-4 rounded-xl border border-cyan-400/25 bg-slate-950/75 p-6 shadow-[0_0_24px_rgba(34,211,238,0.08)]">
            {/* Score circle */}
            <div
              className={`flex h-28 w-28 flex-col items-center justify-center rounded-full border-4 ${palette.ring} ring-[6px] transition-all duration-700`}
              style={{ borderColor: 'currentColor' }}
            >
              <span className={`text-4xl font-black tabular-nums leading-none ${palette.text}`}>
                {score}
              </span>
              <span className="mt-0.5 text-[10px] font-medium uppercase tracking-wider text-slate-400">
                / 5
              </span>
            </div>

            {/* Level badge */}
            {level && (
              <p className="text-center text-sm font-medium text-slate-200">
                {RISK_ICON[level]} <strong>{level} Risk</strong>
              </p>
            )}

            {/* Score bar (1-5 scale) */}
            <div className="w-full">
              <div className="mb-1 flex justify-between text-[10px] font-semibold text-slate-400">
                <span>1</span>
                <span>5</span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800/80">
                <div
                  className={`h-full rounded-full ${palette.bg} transition-all duration-1000 ease-out`}
                  style={{ width: `${Math.min(score, 5) * 20}%` }}
                />
              </div>
            </div>

            {/* Crop type chip */}
            <div className="flex w-full items-center gap-2 rounded-lg border border-cyan-400/20 bg-slate-900/70 px-3 py-2">
              <span className="text-base">🌾</span>
              <div>
                <div className="text-[10px] font-medium uppercase tracking-wider text-slate-400">Crop</div>
                <div className="text-sm font-semibold capitalize text-slate-100">{report.crop_type}</div>
              </div>
              {report.crop_type_in_bbox ? (
                <span className="ml-auto rounded-full bg-emerald-400/20 px-2 py-0.5 text-[10px] font-bold text-emerald-300">✓ in bbox</span>
              ) : (
                <span className="ml-auto rounded-full bg-rose-400/20 px-2 py-0.5 text-[10px] font-bold text-rose-300">✗ not in bbox</span>
              )}
            </div>

            {/* Recommended action */}
            <div
              className={`w-full rounded-lg border px-4 py-3 text-center text-sm font-bold uppercase tracking-wide ${
                ACTION_STYLE[report.recommended_action] ?? 'bg-slate-800/60 text-slate-200 border-slate-600'
              }`}
            >
              Recommended: {report.recommended_action}
            </div>

            {/* Bbox */}
            <div className="w-full text-center text-[10px] text-slate-400">
              bbox: [{report.selected_bbox.join(', ')}]
            </div>
          </div>

          {/* ─── Right: Detail cards ─── */}
          <div className="space-y-3">
            {allDetails.map(([key, value]) => (
              <article
                key={key}
                className="rounded-xl border border-cyan-400/20 bg-slate-950/75 p-4 transition hover:shadow-[0_0_18px_rgba(34,211,238,0.1)]"
              >
                <h3 className="mb-1.5 text-xs font-bold uppercase tracking-wide text-cyan-300">
                  {key}
                </h3>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-200">
                  {value}
                </p>
              </article>
            ))}

            {/* ── Market & Weather Risk table ── */}
            {marketData && (
              <article className="rounded-xl border border-cyan-400/20 bg-slate-950/75 p-4 transition hover:shadow-[0_0_18px_rgba(34,211,238,0.1)]">
                <h3 className="mb-3 text-xs font-bold uppercase tracking-wide text-cyan-300">
                  Market &amp; Weather Risk Assessment
                </h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-700/60">
                        <th className="pb-2 pr-4 text-left text-[11px] font-semibold uppercase tracking-wider text-slate-400">Metric</th>
                        <th className="pb-2 text-right text-[11px] font-semibold uppercase tracking-wider text-slate-400">Value</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(marketData).map(([k, v]) => {
                        const label = MARKET_LABELS[k] ?? k.replace(/_/g, ' ');
                        const formatted = formatMarketValue(k, v);
                        const isRiskField = ['weather_risk_score', 'heat_risk', 'flood_risk'].includes(k);
                        const isTrend = k === 'trend_direction';

                        return (
                          <tr key={k} className="border-b border-slate-800/70 last:border-0">
                            <td className="py-1.5 pr-4 font-medium text-slate-300">{label}</td>
                            <td className="py-1.5 text-right">
                              {isTrend && typeof v === 'string' ? (
                                <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold capitalize ${trendBadge(v)}`}>
                                  {v === 'rising' ? '↑' : v === 'falling' ? '↓' : '→'} {v}
                                </span>
                              ) : isRiskField && typeof v === 'number' ? (
                                <span className={`font-semibold tabular-nums ${riskBadge(v)}`}>{formatted}</span>
                              ) : (
                                <span className="font-semibold tabular-nums text-slate-100">{formatted}</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </article>
            )}

            {allDetails.length === 0 && !marketData && (
              <div className="rounded-xl border border-cyan-400/20 bg-slate-950/75 p-5 text-sm text-slate-400">
                No additional details in this report.
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
