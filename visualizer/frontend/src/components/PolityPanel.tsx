import { useQuery } from '@tanstack/react-query';
import { useAppStore } from '../store';
import { getPolityDetails } from '../api';
import { EvolutionChart } from './EvolutionChart';
import { OccupationsChart } from './OccupationsChart';
import { IndividualsList } from './IndividualsList';

function formatYear(year: number | null): string {
  if (year === null) return '?';
  if (year < 0) {
    return `${Math.abs(year)} BCE`;
  }
  return `${year} CE`;
}

export function PolityPanel() {
  const { selectedPolityId, setSelectedPolityId } = useAppStore();

  const { data: polity } = useQuery({
    queryKey: ['polityDetails', selectedPolityId],
    queryFn: () => (selectedPolityId ? getPolityDetails(selectedPolityId) : Promise.resolve(null)),
    enabled: !!selectedPolityId,
  });

  if (!selectedPolityId) {
    return (
      <div className="py-12 flex items-center justify-center text-gray-400 text-center">
        <div>
          <div className="text-lg mb-2">No polity selected</div>
          <div className="text-sm">Click on a polity on the map to see details</div>
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-start justify-between p-4 border-b border-gray-200">
        <div>
          <h2 className="text-xl font-semibold text-gray-900">{polity?.name ?? 'Loading...'}</h2>
          {polity && (
            <div className="text-sm text-gray-500 mt-1">
              {polity.type && <span className="mr-3">{polity.type}</span>}
              <span>
                {formatYear(polity.from_year)} - {formatYear(polity.to_year)}
              </span>
              {polity.wikipedia_url && (
                <a
                  href={polity.wikipedia_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ml-3 text-blue-600 hover:underline"
                >
                  Wikipedia
                </a>
              )}
            </div>
          )}
        </div>
        <button
          onClick={() => setSelectedPolityId(null)}
          className="text-gray-400 hover:text-gray-600 p-1"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Two-column layout: chart left, individuals right */}
      <div className="flex items-stretch">
        {/* Left: Evolution Chart + Occupations */}
        <div className="w-1/2 p-4 border-r border-gray-200">
          <h3 className="text-sm font-medium text-gray-700 mb-2">Evolution</h3>
          <div className="h-56">
            <EvolutionChart />
          </div>
          <h3 className="text-sm font-medium text-gray-700 mt-4 mb-2">Occupations</h3>
          <div style={{ height: '28rem' }}>
            <OccupationsChart />
          </div>
        </div>

        {/* Right: Individuals List - matches left column height */}
        <div className="w-1/2 p-4 flex flex-col">
          <h3 className="text-sm font-medium text-gray-700 mb-2 flex-shrink-0">Notable Individuals</h3>
          <div className="flex-1 min-h-0">
            <IndividualsList />
          </div>
        </div>
      </div>
    </div>
  );
}
