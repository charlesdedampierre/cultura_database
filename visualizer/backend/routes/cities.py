"""City-related API endpoints."""

from fastapi import APIRouter, Query, HTTPException
from ..database import get_db
from ..models import PolityTopCities, City


router = APIRouter(prefix="/cities", tags=["cities"])


@router.get("/polity/{polity_id}", response_model=PolityTopCities)
def get_polity_top_cities(
    polity_id: int,
    limit: int = Query(10, ge=1, le=50, description="Number of cities to return"),
):
    """Get top cities by individual count for a polity."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Verify polity exists
        cursor.execute("SELECT id FROM polities WHERE id = ?", (polity_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Polity not found")

        # Get top cities from cache (filter out NULL lat/lon)
        cursor.execute("""
            SELECT city_id, city_name, lat, lon, individual_count
            FROM top_cities_cache
            WHERE polity_id = ? AND lat IS NOT NULL AND lon IS NOT NULL
            ORDER BY individual_count DESC
            LIMIT ?
        """, (polity_id, limit))

        rows = cursor.fetchall()

        cities = [
            City(
                city_id=row['city_id'],
                name=row['city_name'],
                lat=row['lat'],
                lon=row['lon'],
                count=row['individual_count']
            )
            for row in rows
        ]

        return PolityTopCities(polity_id=polity_id, cities=cities)


@router.get("/{city_id}")
def get_city(city_id: str):
    """Get city details."""
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM cities WHERE id = ?
        """, (city_id,))

        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="City not found")

        return {
            "id": row['id'],
            "name_en": row['name_en'],
            "lat": row['lat'],
            "lon": row['lon'],
            "iso_country_name": row['iso_country_name'],
        }
