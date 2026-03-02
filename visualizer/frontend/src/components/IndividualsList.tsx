import { useQuery } from '@tanstack/react-query';
import { useAppStore } from '../store';
import { getPolityIndividuals } from '../api';
import type { Individual } from '../types';

const ITEMS_PER_PAGE = 20;

function formatYear(year: number | null): string {
  if (year === null) return '-';
  if (year < 0) {
    return `${Math.abs(year)} BCE`;
  }
  return `${year} CE`;
}

function truncateText(text: string | null, maxLength: number): string {
  if (!text) return '-';
  if (text.length <= maxLength) return text;
  return text.slice(0, maxLength) + '...';
}

export function IndividualsList() {
  const {
    selectedPolityId,
    sortField,
    sortOrder,
    currentPage,
    setSortField,
    toggleSortOrder,
    setCurrentPage,
    filterOccupation,
    setFilterOccupation,
    filterYear,
  } = useAppStore();

  const { data, isLoading, error } = useQuery({
    queryKey: ['polityIndividuals', selectedPolityId, currentPage, sortField, sortOrder, filterYear, filterOccupation],
    queryFn: () =>
      selectedPolityId
        ? getPolityIndividuals(selectedPolityId, currentPage, ITEMS_PER_PAGE, sortField, sortOrder, filterYear, filterOccupation)
        : Promise.resolve(null),
    enabled: !!selectedPolityId,
  });

  if (!selectedPolityId) {
    return (
      <div className="py-8 text-center text-gray-400">
        Select a polity to view individuals
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="py-8 text-center text-gray-400">
        Loading...
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="py-8 text-center text-red-400">
        Error loading data
      </div>
    );
  }

  const totalPages = Math.ceil(data.total / ITEMS_PER_PAGE);

  const handleSort = (field: 'sitelinks_count' | 'impact_date') => {
    if (sortField === field) {
      toggleSortOrder();
    } else {
      setSortField(field);
    }
  };

  const getSortIndicator = (field: 'sitelinks_count' | 'impact_date') => {
    if (sortField !== field) return null;
    return sortOrder === 'asc' ? ' ↑' : ' ↓';
  };

  return (
    <div className="flex flex-col h-full">
      {/* Active filter indicator */}
      {filterOccupation && (
        <div className="mb-2 flex items-center gap-2 flex-shrink-0">
          <span className="text-xs text-gray-500">Filtered by:</span>
          <span
            className="bg-green-100 text-green-700 text-xs px-2 py-0.5 rounded cursor-pointer hover:bg-green-200"
            onClick={() => setFilterOccupation(null)}
          >
            {filterOccupation} ✕
          </span>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-2 flex-shrink-0">
        <span className="text-sm text-gray-500">
          {data.total.toLocaleString()} individual{data.total !== 1 ? 's' : ''}
          {filterOccupation ? ' (filtered)' : ''}
        </span>
        <div className="flex gap-2">
          <button
            onClick={() => handleSort('sitelinks_count')}
            className={`text-xs px-2 py-1 rounded ${
              sortField === 'sitelinks_count'
                ? 'bg-blue-100 text-blue-700'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            Fame{getSortIndicator('sitelinks_count')}
          </button>
          <button
            onClick={() => handleSort('impact_date')}
            className={`text-xs px-2 py-1 rounded ${
              sortField === 'impact_date'
                ? 'bg-blue-100 text-blue-700'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            Date{getSortIndicator('impact_date')}
          </button>
        </div>
      </div>

      {/* Scrollable table */}
      <div className="flex-1 overflow-y-auto min-h-0">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 sticky top-0">
            <tr>
              <th className="text-left px-2 py-1.5 font-medium text-gray-600">Name</th>
              <th className="text-left px-2 py-1.5 font-medium text-gray-600">Occupation</th>
              <th className="text-right px-2 py-1.5 font-medium text-gray-600">Impact Year</th>
              <th className="text-right px-2 py-1.5 font-medium text-gray-600">Fame</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {data.individuals.map((ind: Individual) => (
              <tr key={ind.wikidata_id} className="hover:bg-gray-50">
                <td className="px-2 py-1">
                  <a
                    href={`https://www.wikidata.org/wiki/${ind.wikidata_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 hover:underline"
                  >
                    {truncateText(ind.name_en, 25)}
                  </a>
                </td>
                <td className="px-2 py-1 text-gray-600">
                  {truncateText(ind.occupations_en, 30)}
                </td>
                <td className="px-2 py-1 text-right text-gray-600 whitespace-nowrap">
                  {formatYear(ind.impact_date_raw)}
                </td>
                <td className="px-2 py-1 text-right text-gray-600">
                  {ind.sitelinks_count?.toLocaleString() ?? '-'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-2 border-t border-gray-100 flex-shrink-0">
          <button
            onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
            disabled={currentPage === 1}
            className="px-3 py-1 text-sm bg-gray-100 rounded hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Previous
          </button>
          <span className="text-sm text-gray-500">
            Page {currentPage} of {totalPages}
          </span>
          <button
            onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
            disabled={currentPage === totalPages}
            className="px-3 py-1 text-sm bg-gray-100 rounded hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
