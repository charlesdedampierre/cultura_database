import { useEffect, useRef, useState, useCallback } from 'react';
import maplibregl from 'maplibre-gl';
import { useQuery } from '@tanstack/react-query';
import { useAppStore } from '../store';
import { getActivePolities } from '../api';
import type { PolityWithGeometry } from '../types';

const POLITY_COLORS = [
  '#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6',
  '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1',
];

function makeStyle(projection: 'mercator' | 'globe'): maplibregl.StyleSpecification {
  return {
    version: 8,
    projection: { type: projection } as any,
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
        id: 'carto-light-layer',
        type: 'raster',
        source: 'carto-light',
        minzoom: 0,
        maxzoom: 22,
      },
    ],
  };
}

export function WorldMap() {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [isGlobe, setIsGlobe] = useState(false);

  const { selectedYear, selectedPolityId, setSelectedPolityId } = useAppStore();

  // Store the latest polities data and selection in refs so we can re-apply after style change
  const latestFeaturesRef = useRef<any[]>([]);
  const setSelectedPolityIdRef = useRef(setSelectedPolityId);
  setSelectedPolityIdRef.current = setSelectedPolityId;

  const toggleGlobe = useCallback(() => {
    if (!map.current) return;
    const newIsGlobe = !isGlobe;
    setIsGlobe(newIsGlobe);

    // Set the full style with the new projection; diff:false to force full reload
    map.current.setStyle(makeStyle(newIsGlobe ? 'globe' : 'mercator'), { diff: false });
  }, [isGlobe]);

  // Fetch active polities
  const { data: politiesData, isLoading } = useQuery({
    queryKey: ['activePolities', selectedYear],
    queryFn: () => getActivePolities(selectedYear),
  });

  // Initialize map once
  useEffect(() => {
    if (!mapContainer.current || map.current) return;

    const mapInstance = new maplibregl.Map({
      container: mapContainer.current,
      style: makeStyle('mercator'),
      center: [20, 30],
      zoom: 2.5,
      attributionControl: false,
    });

    mapInstance.addControl(new maplibregl.NavigationControl(), 'top-right');

    // Re-add polity layers whenever the style finishes loading (initial or after setStyle)
    mapInstance.on('style.load', () => {
      // Add polities source if it doesn't exist yet
      if (!mapInstance.getSource('polities')) {
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
      }

      // Re-apply the latest features data
      const source = mapInstance.getSource('polities') as maplibregl.GeoJSONSource;
      if (source && latestFeaturesRef.current.length > 0) {
        source.setData({
          type: 'FeatureCollection',
          features: latestFeaturesRef.current,
        });
      }

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

    // Store in ref so we can re-apply after style changes
    latestFeaturesRef.current = features;

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
      {/* Globe toggle button */}
      <button
        onClick={toggleGlobe}
        className="absolute top-4 left-4 bg-white px-3 py-2 rounded-lg shadow-md text-sm text-gray-700 hover:bg-gray-50 transition-colors flex items-center gap-2 z-10 border border-gray-200"
        title={isGlobe ? 'Switch to flat map' : 'Switch to globe view'}
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="10" strokeWidth={1.5} />
          <path strokeWidth={1.5} d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10A15.3 15.3 0 0 1 12 2z" />
        </svg>
        {isGlobe ? 'Flat Map' : 'Globe'}
      </button>
      {isLoading && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 bg-white px-3 py-2 rounded-lg shadow-md text-sm text-gray-600">
          Loading polities...
        </div>
      )}
      {politiesData && (
        <div className="absolute bottom-4 left-4 bg-white px-3 py-2 rounded-lg shadow-md text-sm text-gray-600">
          {politiesData.polities.length} polities active
        </div>
      )}
    </div>
  );
}
