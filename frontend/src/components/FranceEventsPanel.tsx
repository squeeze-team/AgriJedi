import { useEffect, useState } from 'react';
import { fetchEuropeGdacsEvents, type GdacsEuropeEvent, type GdacsEuropeEventsResponse } from '../services/api';

function alertBadgeClass(level: string) {
  const normalized = level.toLowerCase();
  if (normalized.includes('red')) return 'border-rose-400/50 bg-rose-500/20 text-rose-200';
  if (normalized.includes('orange')) return 'border-amber-400/50 bg-amber-500/20 text-amber-200';
  if (normalized.includes('green')) return 'border-emerald-400/50 bg-emerald-500/20 text-emerald-200';
  return 'border-slate-500/50 bg-slate-700/30 text-slate-200';
}

function formatDate(value: string) {
  if (!value) return 'n/a';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toISOString().slice(0, 10);
}

function EventRow({ event }: { event: GdacsEuropeEvent }) {
  return (
    <div className="rounded-lg border border-cyan-400/20 bg-slate-900/50 px-3 py-2">
      <div className="mb-1 flex items-start justify-between gap-2">
        <p className="text-sm font-semibold text-slate-100">{event.title}</p>
        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase ${alertBadgeClass(event.alert_level)}`}>
          {event.alert_level || 'unknown'}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-300">
        <span>Type: {event.hazard}</span>
        <span>{formatDate(event.start_date)} → {formatDate(event.end_date)}</span>
      </div>
      {event.url ? (
        <a
          href={event.url}
          target="_blank"
          rel="noreferrer"
          className="mt-1 inline-block text-xs font-medium text-cyan-300 hover:text-cyan-200"
        >
          Open details
        </a>
      ) : null}
    </div>
  );
}

export function FranceEventsPanel() {
  const [data, setData] = useState<GdacsEuropeEventsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadEvents() {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchEuropeGdacsEvents(14, 8);
      setData(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadEvents();
    const timer = window.setInterval(() => {
      void loadEvents();
    }, 10 * 60 * 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <section className="panel-card">
      <div className="panel-title flex items-center justify-between gap-2">
        <span>Europe Hazard Events (GDACS)</span>
        <button
          type="button"
          onClick={() => void loadEvents()}
          className="rounded-md border border-cyan-400/40 px-2 py-0.5 text-[10px] font-semibold text-cyan-200 hover:bg-cyan-400/10"
        >
          Refresh
        </button>
      </div>
      <div className="space-y-2 p-3">
        {loading && (
          <div className="flex min-h-[260px] items-center justify-center text-center text-sm text-slate-400">
            Checking GDACS feed...
          </div>
        )}
        {!loading && error && (
          <div className="rounded-lg border border-rose-400/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            GDACS unavailable: {error}
          </div>
        )}
        {!loading && !error && data?.feed_ok === false && (
          <div className="rounded-lg border border-amber-400/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
            {data.message || 'GDACS feed unavailable'}
          </div>
        )}
        {!loading && !error && data?.all_good && (
          <div className="rounded-lg border border-emerald-400/40 bg-emerald-500/10 px-3 py-2 text-sm font-semibold text-emerald-200">
            No active hazard events detected in Europe.
          </div>
        )}
        {!loading && !error && data && data.events.length > 0 && (
          <div className="max-h-[320px] space-y-2 overflow-y-auto pr-1">
            {data.events.map((event) => (
              <EventRow key={`${event.id}-${event.start_date}`} event={event} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
