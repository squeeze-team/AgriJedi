import { useEffect } from 'react';
import { MapContainer, Rectangle, TileLayer, WMSTileLayer, useMap } from 'react-leaflet';

const CLMS_WMS_URL = 'https://geoserver.vlcc.geoville.com/geoserver/ows';
const CLMS_LAYER = 'HRL_CPL:CTY_S2021';

type Bounds = [[number, number], [number, number]];

interface MapPanelProps {
  bbox: string;
}

function parseBboxToBounds(bbox: string): Bounds | null {
  const values = bbox.split(',').map((value) => Number(value.trim()));
  if (values.length !== 4 || values.some((value) => Number.isNaN(value))) {
    return null;
  }

  const [west, south, east, north] = values;
  return [[south, west], [north, east]];
}

function AutoFitBounds({ bounds }: { bounds: Bounds | null }) {
  const map = useMap();

  useEffect(() => {
    if (!bounds) {
      return;
    }
    const fitToBounds = () => {
      const size = map.getSize();
      const verticalPadding = Math.round(size.y * 0.1);
      const horizontalPadding = Math.round(size.x * 0.08);

      map.fitBounds(bounds, {
        paddingTopLeft: [horizontalPadding, verticalPadding],
        paddingBottomRight: [horizontalPadding, verticalPadding],
        animate: true,
        duration: 0.45,
        // Keep zoom in a range where CLMS crop tiles remain readable/visible.
        maxZoom: 14,
      });
    };

    map.invalidateSize();
    fitToBounds();
  }, [map, bounds]);

  return null;
}

export function MapPanel({ bbox }: MapPanelProps) {
  const bounds = parseBboxToBounds(bbox);

  return (
    <section className="panel-card">
      <div className="panel-title">Crop Distribution - CLMS + Sentinel-2</div>
      <div className="relative h-[420px] w-full">
        <MapContainer center={[46.6, 2.5]} zoom={6} className="h-full w-full">
          <AutoFitBounds bounds={bounds} />
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution="&copy; OpenStreetMap contributors"
          />
          <WMSTileLayer
            url={CLMS_WMS_URL}
            layers={CLMS_LAYER}
            format="image/png"
            transparent
            version="1.3.0"
            opacity={0.72}
          />
          {bounds && (
            <Rectangle
              bounds={bounds}
              pathOptions={{
                color: '#e11d48',
                weight: 2,
                fillOpacity: 0.1,
                dashArray: '6 4',
              }}
            />
          )}
        </MapContainer>

        <div className="map-legend absolute bottom-4 right-3 z-[500] w-[170px] rounded-lg bg-white/90 p-2 shadow-md">
          <h4 className="mb-1 text-xs font-semibold text-slate-700">Crop Types 2021</h4>
          <ul className="space-y-1 text-xs text-slate-700">
            <li className="flex items-center gap-2">
              <span className="inline-block h-3 w-3 rounded-[2px] bg-[#f4de7a]" />
              Maize
            </li>
            <li className="flex items-center gap-2">
              <span className="inline-block h-3 w-3 rounded-[2px] bg-[#d8b47f]" />
              Wheat
            </li>
            <li className="flex items-center gap-2">
              <span className="inline-block h-3 w-3 rounded-[2px] bg-[#e7a5c8]" />
              Grapes
            </li>
          </ul>
        </div>
      </div>
    </section>
  );
}
