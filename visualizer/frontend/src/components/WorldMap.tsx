import { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import { useQuery } from '@tanstack/react-query';
import { useAppStore } from '../store';
import { getActivePolities } from '../api';
import type { PolityWithGeometry } from '../types';

const POLITY_COLORS = [
  '#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6',
  '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1',
];

const MAP_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    'carto-light': {
      type: 'raster',
      tiles: [
        'https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png',
        'https://b.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png',
        'https://c.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png',
      ],
      tileSize: 256,
      attribution: '',
    },
  },
  layers: [
    {
      id: 'background',
      type: 'background',
      paint: { 'background-color': '#e8e8e8' },
    },
    {
      id: 'carto-light-layer',
      type: 'raster',
      source: 'carto-light',
      minzoom: 0,
      maxzoom: 22,
    },
  ],
};

export function WorldMap() {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [mapReady, setMapReady] = useState(false);

  const { selectedYear, selectedPolityId, setSelectedPolityId, hierarchyMode, setHierarchyMode } = useAppStore();

  const setSelectedPolityIdRef = useRef(setSelectedPolityId);
  setSelectedPolityIdRef.current = setSelectedPolityId;

  // Fetch active polities
  const { data: politiesData, isLoading, error } = useQuery({
    queryKey: ['activePolities', selectedYear, hierarchyMode],
    queryFn: () => getActivePolities(selectedYear, hierarchyMode),
  });

  // Initialize map once
  useEffect(() => {
    if (!mapContainer.current || map.current) return;

    const mapInstance = new maplibregl.Map({
      container: mapContainer.current,
      style: MAP_STYLE,
      center: [20, 30],
      zoom: 2.5,
      attributionControl: false,
    });

    mapInstance.addControl(new maplibregl.NavigationControl(), 'top-right');

    mapInstance.on('load', () => {
      mapInstance.addSource('polities', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });

      mapInstance.addLayer({
        id: 'polities-fill',
        type: 'fill',
        source: 'polities',
        paint: {
          'fill-color': ['get', 'color'],
          'fill-opacity': ['case', ['get', 'selected'], 0.6, 0.3],
        },
      });

      mapInstance.addLayer({
        id: 'polities-outline',
        type: 'line',
        source: 'polities',
        paint: {
          'line-color': ['get', 'color'],
          'line-width': ['case', ['get', 'selected'], 3, 1],
        },
      });

      mapInstance.on('click', 'polities-fill', (e) => {
        if (e.features && e.features.length > 0) {
          const polityId = e.features[0].properties?.id;
          if (polityId) {
            setSelectedPolityIdRef.current(polityId);
          }
        }
      });

      mapInstance.on('mouseenter', 'polities-fill', () => {
        mapInstance.getCanvas().style.cursor = 'pointer';
      });
      mapInstance.on('mouseleave', 'polities-fill', () => {
        mapInstance.getCanvas().style.cursor = '';
      });

      setMapReady(true);
    });

    map.current = mapInstance;

    return () => {
      mapInstance.remove();
      map.current = null;
    };
  }, []);

  // Update polities data when year changes or selection changes
  useEffect(() => {
    if (!map.current || !mapReady || !politiesData) return;

    const features = politiesData.polities
      .filter((polity: PolityWithGeometry) => polity.geometry)
      .map((polity: PolityWithGeometry) => ({
        type: 'Feature' as const,
        properties: {
          id: polity.id,
          name: polity.name,
          color: POLITY_COLORS[polity.id % POLITY_COLORS.length],
          selected: polity.id === selectedPolityId,
        },
        geometry: polity.geometry!,
      }));

    const source = map.current.getSource('polities') as maplibregl.GeoJSONSource;
    if (source) {
      source.setData({
        type: 'FeatureCollection',
        features,
      });
    }
  }, [politiesData, selectedPolityId, mapReady]);

  return (
    <div className="absolute inset-0">
      <div ref={mapContainer} className="absolute inset-0" />
      {/* Hierarchy toggle button */}
      <button
        onClick={() => setHierarchyMode(hierarchyMode === 'leaf' ? 'aggregate' : 'leaf')}
        className={`absolute top-4 left-4 px-3 py-2 rounded-lg shadow-md text-sm transition-colors flex items-center gap-2 z-10 border ${
          hierarchyMode === 'aggregate'
            ? 'bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100'
            : 'bg-white text-gray-700 border-gray-200 hover:bg-gray-50'
        }`}
        title={hierarchyMode === 'leaf' ? 'Switch to larger polity groupings (empires)' : 'Switch to smaller polities'}
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
            d={hierarchyMode === 'leaf'
              ? "M4 6h16M4 12h16M4 18h16"
              : "M3 4h18v6H3zM3 14h18v6H3z"
            }
          />
        </svg>
        {hierarchyMode === 'leaf' ? 'Polities' : 'Empires'}
      </button>
      {isLoading && (
        <div className="absolute top-4 left-32 bg-white px-3 py-2 rounded-lg shadow-md text-sm text-gray-600">
          Loading...
        </div>
      )}
      {error && (
        <div className="absolute top-4 left-32 bg-red-50 text-red-700 px-3 py-2 rounded-lg shadow-md text-sm">
          Error: {(error as Error).message}
        </div>
      )}
      {politiesData && (
        <div className="absolute bottom-4 left-4 bg-white px-3 py-2 rounded-lg shadow-md text-sm text-gray-600">
          {politiesData.polities.length} {hierarchyMode === 'leaf' ? 'polities' : 'empires'} active
        </div>
      )}
    </div>
  );
}
