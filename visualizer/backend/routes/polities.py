"""Polity-related API endpoints."""

import json
from fastapi import APIRouter, Query, HTTPException
from typing import Literal
from ..database import get_db, dicts_from_rows
from ..models import (
    ActivePolitiesResponse,
    PolityWithGeometry,
    PolityEvolution,
    EvolutionPoint,
)


router = APIRouter(prefix="/polities", tags=["polities"])


def round_to_25(year: int) -> int:
    """Round year to nearest 25."""
    return round(year / 25) * 25


# Which display_mode values to show for each hierarchy level
HIERARCHY_FILTERS = {
    "leaf": ("both", "leaf"),
    "aggregate": ("both", "aggregate"),
}


@router.get("/active", response_model=ActivePolitiesResponse)
def get_active_polities(
    year: int = Query(..., description="Year (will be rounded to nearest 25)"),
    hierarchy: Literal["leaf", "aggregate"] = Query(
        "leaf", description="Hierarchy level: 'leaf' for smaller polities (default), 'aggregate' for larger groupings"
    ),
):
    """Get all polities active at a specific year with their geometries."""
    # Round to nearest 25
    rounded_year = round_to_25(year)
    allowed_modes = HIERARCHY_FILTERS[hierarchy]

    with get_db() as conn:
        cursor = conn.cursor()

        # Get polities active at this year, filtered by hierarchy display_mode
        cursor.execute("""
            SELECT
                p.id,
                p.name,
                p.type,
                pp.from_year,
                pp.to_year,
                pp.geometry
            FROM polity_periods pp
            JOIN polities p ON pp.polity_id = p.id
            WHERE pp.from_year <= ? AND pp.to_year >= ?
              AND p.display_mode IN (?, ?)
        """, (rounded_year, rounded_year, allowed_modes[0], allowed_modes[1]))

        rows = cursor.fetchall()

        polities = []
        for row in rows:
            geometry = None
            if row['geometry']:
                try:
                    geometry = json.loads(row['geometry'])
                except json.JSONDecodeError:
                    pass

            polities.append(PolityWithGeometry(
                id=row['id'],
                name=row['name'],
                type=row['type'],
                from_year=row['from_year'],
                to_year=row['to_year'],
                geometry=geometry
            ))

        return ActivePolitiesResponse(year=rounded_year, polities=polities)


@router.get("/{polity_id}/evolution", response_model=PolityEvolution)
def get_polity_evolution(polity_id: int):
    """Get individual count per 25-year period for a polity."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Get polity info
        cursor.execute("""
            SELECT id, name FROM polities WHERE id = ?
        """, (polity_id,))
        polity = cursor.fetchone()

        if not polity:
            raise HTTPException(status_code=404, detail="Polity not found")

        # Get polity lifespan
        cursor.execute("""
            SELECT MIN(from_year) as from_year, MAX(to_year) as to_year
            FROM polity_periods WHERE polity_id = ?
        """, (polity_id,))
        lifespan = cursor.fetchone()

        # Get evolution data
        cursor.execute("""
            SELECT year, count
            FROM evolution_cache
            WHERE polity_id = ?
            ORDER BY year
        """, (polity_id,))

        rows = cursor.fetchall()

        evolution = [
            EvolutionPoint(year=row['year'], count=row['count'])
            for row in rows
        ]

        return PolityEvolution(
            polity_id=polity_id,
            polity_name=polity['name'],
            from_year=lifespan['from_year'] if lifespan else None,
            to_year=lifespan['to_year'] if lifespan else None,
            evolution=evolution
        )


@router.get("/{polity_id}")
def get_polity(polity_id: int):
    """Get polity details."""
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM polities WHERE id = ?
        """, (polity_id,))

        polity = cursor.fetchone()

        if not polity:
            raise HTTPException(status_code=404, detail="Polity not found")

        # Get lifespan
        cursor.execute("""
            SELECT MIN(from_year) as from_year, MAX(to_year) as to_year
            FROM polity_periods WHERE polity_id = ?
        """, (polity_id,))
        lifespan = cursor.fetchone()

        return {
            "id": polity['id'],
            "name": polity['name'],
            "type": polity['type'],
            "wikipedia_url": polity['wikipedia_url'],
            "wikidata_id": polity['wikidata_id'],
            "individuals_count": polity['individuals_count'],
            "from_year": lifespan['from_year'] if lifespan else None,
            "to_year": lifespan['to_year'] if lifespan else None,
        }
