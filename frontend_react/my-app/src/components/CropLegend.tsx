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

export function CropLegend({ className = '', title = 'Crop Types 2021', items }: CropLegendProps) {
  const legendItems = items && items.length > 0 ? items : defaultCropLegendItems;

  return (
    <div className={`w-[170px] rounded-lg bg-white/90 p-2 shadow-md ${className}`}>
      <h4 className="mb-1 text-xs font-semibold text-slate-700">{title}</h4>
      <ul className="space-y-1 text-xs text-slate-700">
        {legendItems.map((item) => (
          <li key={item.label} className="flex items-center gap-2">
            <span className="inline-block h-3 w-3 rounded-[2px]" style={{ backgroundColor: item.color }} />
            {item.label}
          </li>
        ))}
      </ul>
    </div>
  );
}
