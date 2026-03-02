"""Individual-related API endpoints."""

import logging
from fastapi import APIRouter, Query, HTTPException
from typing import Literal
from ..database import get_db
from ..models import PaginatedIndividuals, Individual

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/individuals", tags=["individuals"])


@router.get("/polity/{polity_id}", response_model=PaginatedIndividuals)
def get_polity_individuals(
    polity_id: int,
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=200, description="Items per page"),
    sort: Literal["sitelinks_count", "impact_date"] = Query(
        "sitelinks_count", description="Sort field"
    ),
    order: Literal["asc", "desc"] = Query("desc", description="Sort order"),
    impact_year: int | None = Query(None, description="Filter by impact year bucket"),
    occupation: str | None = Query(None, description="Filter by occupation"),
):
    """Get paginated list of individuals for a polity."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Verify polity exists
        cursor.execute("SELECT id FROM polities WHERE id = ?", (polity_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Polity not found")

        # Build WHERE clause with optional filters
        where = "polity_id = ? AND impact_date IS NOT NULL"
        params: list = [polity_id]

        if impact_year is not None:
            where += " AND impact_date = ?"
            params.append(impact_year)

        if occupation is not None:
            logger.info(f"Filtering by occupation: {occupation}")
            where += " AND (occupations_en = ? OR occupations_en LIKE ? OR occupations_en LIKE ? OR occupations_en LIKE ?)"
            params.extend([occupation, f"{occupation}; %", f"%; {occupation}; %", f"%; {occupation}"])
            logger.info(f"WHERE clause: {where}, params: {params}")

        # Get total count
        cursor.execute(f"SELECT COUNT(*) as cnt FROM individuals_light WHERE {where}", params)
        total = cursor.fetchone()['cnt']

        # Get paginated individuals
        offset = (page - 1) * limit
        order_clause = "DESC" if order == "desc" else "ASC"

        if sort == "sitelinks_count":
            sort_clause = f"sitelinks_count {order_clause}"
        else:
            sort_clause = f"impact_date {order_clause}"

        cursor.execute(f"""
            SELECT
                wikidata_id,
                name_en,
                occupations_en,
                sitelinks_count,
                impact_date,
                impact_date_raw
            FROM individuals_light
            WHERE {where}
            ORDER BY {sort_clause}
            LIMIT ? OFFSET ?
        """, params + [limit, offset])

        rows = cursor.fetchall()

        individuals = [
            Individual(
                wikidata_id=row['wikidata_id'],
                name_en=row['name_en'],
                occupations_en=row['occupations_en'],
                sitelinks_count=row['sitelinks_count'],
                impact_date=row['impact_date'],
                impact_date_raw=row['impact_date_raw']
            )
            for row in rows
        ]

        return PaginatedIndividuals(
            polity_id=polity_id,
            total=total,
            page=page,
            limit=limit,
            individuals=individuals
        )


@router.get("/{wikidata_id}")
def get_individual(wikidata_id: str):
    """Get individual details."""
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DISTINCT
                wikidata_id,
                name_en,
                occupations_en,
                sitelinks_count,
                impact_date,
                birthcity_id,
                deathcity_id
            FROM individuals_light
            WHERE wikidata_id = ?
        """, (wikidata_id,))

        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Individual not found")

        # Get birth city info if available
        birthcity = None
        if row['birthcity_id']:
            cursor.execute("""
                SELECT name_en, lat, lon FROM cities WHERE id = ?
            """, (row['birthcity_id'],))
            bc = cursor.fetchone()
            if bc:
                birthcity = {
                    "id": row['birthcity_id'],
                    "name": bc['name_en'],
                    "lat": bc['lat'],
                    "lon": bc['lon']
                }

        # Get death city info if available
        deathcity = None
        if row['deathcity_id']:
            cursor.execute("""
                SELECT name_en, lat, lon FROM cities WHERE id = ?
            """, (row['deathcity_id'],))
            dc = cursor.fetchone()
            if dc:
                deathcity = {
                    "id": row['deathcity_id'],
                    "name": dc['name_en'],
                    "lat": dc['lat'],
                    "lon": dc['lon']
                }

        return {
            "wikidata_id": row['wikidata_id'],
            "name_en": row['name_en'],
            "occupations_en": row['occupations_en'],
            "sitelinks_count": row['sitelinks_count'],
            "impact_date": row['impact_date'],
            "birthcity": birthcity,
            "deathcity": deathcity,
            "wikidata_url": f"https://www.wikidata.org/wiki/{row['wikidata_id']}"
        }
