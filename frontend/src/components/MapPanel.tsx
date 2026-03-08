import { useEffect, useMemo, useRef } from 'react';
import type { Rectangle as LeafletRectangle } from 'leaflet';
import { MapContainer, Rectangle, TileLayer, WMSTileLayer, useMap } from 'react-leaflet';
import { CropLegend, type CropLegendItem } from './CropLegend';

const CLMS_WMS_URL = 'https://geoserver.vlcc.geoville.com/geoserver/ows';
const CLMS_LAYER = 'HRL_CPL:CTY_S2021';

type Bounds = [[number, number], [number, number]];

interface MapPanelProps {
  bbox: string;
  legendItems?: CropLegendItem[];
}

function parseBboxToBounds(bbox: string): Bounds | null {
  const values = bbox.split(',').map((value) => Number(value.trim()));
  if (values.length !== 4 || values.some((value) => Number.isNaN(value))) {
    return null;
  }

  const [west, south, east, north] = values;
  return [[south, west], [north, east]];
}

function AutoFitBounds({ bounds, bboxKey }: { bounds: Bounds | null; bboxKey: string }) {
  const map = useMap();
  const lastAppliedKeyRef = useRef<string>('');

  useEffect(() => {
    if (!bounds) {
      return;
    }
    if (bboxKey === lastAppliedKeyRef.current) {
      return;
    }

    lastAppliedKeyRef.current = bboxKey;

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
  }, [map, bounds, bboxKey]);

  return null;
}

export function MapPanel({ bbox, legendItems }: MapPanelProps) {
  const bounds = useMemo(() => parseBboxToBounds(bbox), [bbox]);
  const rectangleRef = useRef<LeafletRectangle | null>(null);
  const bboxKey = useMemo(() => {
    const normalized = bbox
      .split(',')
      .map((value) => value.trim())
      .join(',');
    return normalized;
  }, [bbox]);

  useEffect(() => {
    if (!bounds) {
      return;
    }
    let rafId = 0;
    const animate = (timestamp: number) => {
      const layer = rectangleRef.current;
      if (layer) {
        // Marching-ants effect for bbox stroke, robust across production builds.
        const offset = -((timestamp * 0.012) % 28);
        layer.setStyle({ dashOffset: `${offset.toFixed(1)}` });
      }
      rafId = window.requestAnimationFrame(animate);
    };
    rafId = window.requestAnimationFrame(animate);
    return () => window.cancelAnimationFrame(rafId);
  }, [bboxKey, bounds]);

  return (
    <section className="panel-card">
      <div className="panel-title">Regional Crop Distribution</div>
      <div className="relative h-[420px] w-full">
        <MapContainer center={[46.6, 2.5]} zoom={6} preferCanvas={false} className="h-full w-full">
          <AutoFitBounds bounds={bounds} bboxKey={bboxKey} />
          <TileLayer
            url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
            attribution="&copy; OpenStreetMap contributors &copy; CARTO"
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
              ref={rectangleRef}
              bounds={bounds}
              pathOptions={{
                className: 'cyber-bbox-rect',
                color: '#ff4fd8',
                weight: 2.4,
                fillColor: '#f72585',
                fillOpacity: 0.12,
                dashArray: '8 6',
              }}
            />
          )}
        </MapContainer>

        <CropLegend className="map-legend absolute bottom-4 right-3 z-[500]" items={legendItems} />
      </div>
    </section>
  );
}
