import { create } from 'zustand';

interface AppState {
  // Timeline
  selectedYear: number;
  setSelectedYear: (year: number) => void;

  // Hierarchy toggle
  hierarchyMode: 'leaf' | 'aggregate';
  setHierarchyMode: (mode: 'leaf' | 'aggregate') => void;

  // Selected polity
  selectedPolityId: number | null;
  setSelectedPolityId: (id: number | null) => void;

  // Individuals sorting
  sortField: 'sitelinks_count' | 'impact_date';
  sortOrder: 'asc' | 'desc';
  setSortField: (field: 'sitelinks_count' | 'impact_date') => void;
  toggleSortOrder: () => void;

  // Pagination
  currentPage: number;
  setCurrentPage: (page: number) => void;

  // Filters
  filterYear: number | null;
  setFilterYear: (year: number | null) => void;
  filterOccupation: string | null;
  setFilterOccupation: (occupation: string | null) => void;
  clearFilters: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  // Timeline - default to 1500 CE
  selectedYear: 1500,
  setSelectedYear: (year) => set({ selectedYear: year, currentPage: 1 }),

  // Hierarchy toggle - default to leaf (smaller polities)
  hierarchyMode: 'leaf',
  setHierarchyMode: (mode) => set({
    hierarchyMode: mode,
    selectedPolityId: null,
    currentPage: 1,
    filterYear: null,
    filterOccupation: null,
  }),

  // Selected polity
  selectedPolityId: null,
  setSelectedPolityId: (id) => set({
    selectedPolityId: id,
    currentPage: 1,
    filterYear: null,
    filterOccupation: null,
  }),

  // Individuals sorting
  sortField: 'sitelinks_count',
  sortOrder: 'desc',
  setSortField: (field) => set({ sortField: field, currentPage: 1 }),
  toggleSortOrder: () =>
    set((state) => ({
      sortOrder: state.sortOrder === 'asc' ? 'desc' : 'asc',
      currentPage: 1,
    })),

  // Pagination
  currentPage: 1,
  setCurrentPage: (page) => set({ currentPage: page }),

  // Filters
  filterYear: null,
  setFilterYear: (year) => set((state) => ({
    filterYear: year === null ? null : (state.filterYear === year ? null : year),
    currentPage: 1,
  })),
  filterOccupation: null,
  setFilterOccupation: (occupation) => set((state) => ({
    filterOccupation: occupation === null ? null : (state.filterOccupation === occupation ? null : occupation),
    currentPage: 1,
  })),
  clearFilters: () => set({ filterYear: null, filterOccupation: null, currentPage: 1 }),
}));
