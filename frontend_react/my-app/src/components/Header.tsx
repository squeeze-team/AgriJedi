import type { Crop } from '../services/api';

interface HeaderProps {
  crop: Crop;
  onCropChange: (crop: Crop) => void;
  onRunPrediction: () => void;
}

export function Header({ crop, onCropChange, onRunPrediction }: HeaderProps) {
  return (
    <header className="flex flex-wrap items-center gap-4 bg-blue-600 px-5 py-4 text-white shadow-sm md:px-7">
      <h1 className="text-xl font-bold">AgriIntel</h1>

      <label className="text-sm">
        Crop:
        <select
          className="ml-2 rounded-md border border-blue-200 bg-white px-3 py-1 text-slate-800 outline-none"
          value={crop}
          onChange={(event) => onCropChange(event.target.value as Crop)}
        >
          <option value="wheat">Wheat</option>
          <option value="maize">Maize</option>
          <option value="grape">Grape</option>
        </select>
      </label>

      <span className="text-sm">
        Country: <strong>France</strong>
      </span>

      <div className="ml-auto">
        <button
          type="button"
          onClick={onRunPrediction}
          className="rounded-md bg-white px-4 py-2 text-sm font-semibold text-blue-700 transition hover:bg-blue-100"
        >
          Run Prediction
        </button>
      </div>
    </header>
  );
}
