"""Pydantic models for the visualizer API."""

from pydantic import BaseModel
from typing import Optional, Any


class Polity(BaseModel):
    """Polity model."""
    id: int
    name: str
    type: Optional[str] = None
    wikipedia_url: Optional[str] = None
    wikidata_id: Optional[str] = None
    individuals_count: Optional[int] = None


class PolityPeriod(BaseModel):
    """Polity period with geometry."""
    id: int
    polity_id: int
    polity_name: str
    from_year: int
    to_year: int
    area: Optional[float] = None
    geometry: Optional[Any] = None  # GeoJSON object


class PolityWithGeometry(BaseModel):
    """Polity with its geometry for the current time period."""
    id: int
    name: str
    type: Optional[str] = None
    from_year: int
    to_year: int
    geometry: Optional[Any] = None


class EvolutionPoint(BaseModel):
    """Evolution data point."""
    year: int
    count: int


class PolityEvolution(BaseModel):
    """Polity evolution over time."""
    polity_id: int
    polity_name: str
    from_year: Optional[int] = None
    to_year: Optional[int] = None
    evolution: list[EvolutionPoint]


class City(BaseModel):
    """City model."""
    city_id: str
    name: str
    lat: float
    lon: float
    count: int


class PolityTopCities(BaseModel):
    """Top cities for a polity."""
    polity_id: int
    cities: list[City]


class Individual(BaseModel):
    """Individual model for list display."""
    wikidata_id: str
    name_en: Optional[str] = None
    occupations_en: Optional[str] = None
    sitelinks_count: Optional[int] = None
    impact_date: Optional[int] = None
    impact_date_raw: Optional[int] = None


class PaginatedIndividuals(BaseModel):
    """Paginated list of individuals."""
    polity_id: int
    total: int
    page: int
    limit: int
    individuals: list[Individual]


class ActivePolitiesResponse(BaseModel):
    """Response for active polities at a year."""
    year: int
    polities: list[PolityWithGeometry]
