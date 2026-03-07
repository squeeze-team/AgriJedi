interface CropLegendProps {
  className?: string;
  title?: string;
  items?: CropLegendItem[];
}

export interface CropLegendItem {
  label: string;
  color: string;
}

const defaultCropLegendItems: CropLegendItem[] = [
  { label: 'Maize', color: '#f4de7a' },
  { label: 'Wheat', color: '#d8b47f' },
  { label: 'Grapes', color: '#e7a5c8' },
];

export function CropLegend({ className = '', title = 'Crop Types', items }: CropLegendProps) {
  const legendItems = items && items.length > 0 ? items : defaultCropLegendItems;

  return (
    <div className={`w-[180px] rounded-lg border border-cyan-300/30 bg-slate-950/85 p-2 shadow-[0_0_24px_rgba(34,211,238,0.14)] backdrop-blur ${className}`}>
      <h4 className="mb-1 text-xs font-semibold tracking-[0.08em] text-cyan-200">{title}</h4>
      <ul className="space-y-1 text-xs text-slate-200">
        {legendItems.map((item) => (
          <li key={item.label} className="flex items-center gap-2">
            <span className="inline-block h-3 w-3 rounded-[2px] ring-1 ring-white/30" style={{ backgroundColor: item.color }} />
            {item.label}
          </li>
        ))}
      </ul>
    </div>
  );
}
