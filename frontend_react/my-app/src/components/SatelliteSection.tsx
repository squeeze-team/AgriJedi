import type { SatelliteLayer } from '../services/api';

interface SatelliteViewState {
  src: string | null;
  status: 'idle' | 'loading' | 'loaded' | 'error';
}

interface SatelliteSectionProps {
  bbox: string;
  date: string;
  views: Record<SatelliteLayer, SatelliteViewState>;
  onBboxChange: (bbox: string) => void;
  onDateChange: (date: string) => void;
  onLoad: () => void;
  onImageLoad: (layer: SatelliteLayer) => void;
  onImageError: (layer: SatelliteLayer) => void;
}

const presets = [
  { label: 'Rhone Valley', value: '4.67,44.71,4.97,45.01' },
  { label: 'Beauce (Paris Basin)', value: '1.2,47.8,1.8,48.3' },
  { label: 'Champagne', value: '3.0,49.0,3.8,49.4' },
  { label: 'Bordeaux', value: '-0.8,44.6,0.0,45.1' },
] as const;

const panels: Array<{ layer: SatelliteLayer; title: string; emptyText: string }> = [
  { layer: 'rgb', title: 'True Color (RGB)', emptyText: 'Select a region and click Load.' },
  { layer: 'false_color', title: 'False Color (NIR-R-G)', emptyText: '-' },
  { layer: 'ndvi', title: 'NDVI - Vegetation Health', emptyText: '-' },
  { layer: 'overlay', title: 'RGB + CLMS Crop Types Overlay', emptyText: '-' },
];

export function SatelliteSection({
  bbox,
  date,
  views,
  onBboxChange,
  onDateChange,
  onLoad,
  onImageLoad,
  onImageError,
}: SatelliteSectionProps) {
  return (
    <section className="mx-auto w-full max-w-[1400px] px-5 pb-7 md:px-7">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-bold text-slate-800">Satellite Imagery - Sentinel-2 + CLMS</h2>

        <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600">
          <label className="flex items-center gap-1">
            Region:
            <select
              className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800"
              onChange={(event) => onBboxChange(event.target.value)}
              value={presets.some((preset) => preset.value === bbox) ? bbox : 'custom'}
            >
              {presets.map((preset) => (
                <option key={preset.label} value={preset.value}>
                  {preset.label}
                </option>
              ))}
              <option value="custom">Custom...</option>
            </select>
          </label>

          <label className="flex items-center gap-1">
            BBox:
            <input
              className="w-[230px] rounded-md border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800"
              value={bbox}
              onChange={(event) => onBboxChange(event.target.value)}
            />
          </label>

          <label className="flex items-center gap-1">
            Date:
            <input
              className="w-[200px] rounded-md border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800"
              value={date}
              onChange={(event) => onDateChange(event.target.value)}
            />
          </label>

          <button
            type="button"
            onClick={onLoad}
            className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-semibold text-white transition hover:bg-blue-700"
          >
            Load
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {panels.map((panel) => {
          const view = views[panel.layer];
          const placeholderText =
            view.status === 'loading'
              ? 'Loading...'
              : view.status === 'error'
                ? 'Failed to load - backend may be unavailable.'
                : panel.emptyText;

          return (
            <article key={panel.layer} className="panel-card overflow-hidden">
              <h3 className="panel-title">{panel.title}</h3>
              <div className="relative flex min-h-[320px] items-center justify-center bg-slate-100">
                {(view.status === 'idle' || view.status === 'loading' || view.status === 'error') && (
                  <div className="px-4 text-center text-sm text-slate-500">{placeholderText}</div>
                )}
                {view.src && (
                  <img
                    src={view.src}
                    alt={panel.title}
                    className={`h-auto w-full ${view.status === 'loaded' ? 'block' : 'hidden'}`}
                    onLoad={() => onImageLoad(panel.layer)}
                    onError={() => onImageError(panel.layer)}
                  />
                )}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
