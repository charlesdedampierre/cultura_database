// API Response Types

export interface PolityWithGeometry {
  id: number;
  name: string;
  type: string | null;
  from_year: number;
  to_year: number;
  geometry: GeoJSON.Geometry | null;
}

export interface ActivePolitiesResponse {
  year: number;
  polities: PolityWithGeometry[];
}

export interface EvolutionPoint {
  year: number;
  count: number;
}

export interface PolityEvolution {
  polity_id: number;
  polity_name: string;
  from_year: number | null;
  to_year: number | null;
  evolution: EvolutionPoint[];
}

export interface City {
  city_id: string;
  name: string;
  lat: number;
  lon: number;
  count: number;
}

export interface PolityTopCities {
  polity_id: number;
  cities: City[];
}

export interface Individual {
  wikidata_id: string;
  name_en: string | null;
  occupations_en: string | null;
  sitelinks_count: number | null;
  impact_date: number | null;
  impact_date_raw: number | null;
}

export interface PaginatedIndividuals {
  polity_id: number;
  total: number;
  page: number;
  limit: number;
  individuals: Individual[];
}

export interface PolityDetails {
  id: number;
  name: string;
  type: string | null;
  wikipedia_url: string | null;
  wikidata_id: string | null;
  individuals_count: number | null;
  from_year: number | null;
  to_year: number | null;
}
