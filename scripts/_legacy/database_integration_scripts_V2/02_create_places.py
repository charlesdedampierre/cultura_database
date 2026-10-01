"""02 — Create the `places` reference table from v2 place metadata.

(Was `cities` before the 2026-05 cleanup; renamed because the table
holds every P19/P20 location, not just urban settlements.)

Inputs : data/all_humans/wikidata_extraction_scripts_v2/place_metadata.json
            (one entry per place QID used as a P19 / P20 of any Q5 human)
         data/all_humans/wikidata_extraction_scripts_v2/modern_countries.json
            (Q-id -> {name, iso_a3_code, continent, ...} — used only as a
            lookup to fill `places.country_name`. There is no
            `modern_country` table in the database any more; the raw
            country data was archived to data/legacy_regions/.)
Output : places (id PK, name_en, lat, lon, country_id, country_name,
                 entity_type_ids, en_wikipedia_url)

Usage
-----
    python3 02_create_places.py            # tiny synthetic JSON
    python3 02_create_places.py --full     # data/humans_v2.duckdb
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import duckdb

from common import (
    WIKIDATA_V2_DIR,
    log,
    load_json,
    open_db,
    parse_run_mode,
)


JSON_PATH = WIKIDATA_V2_DIR / "place_metadata.json"
COUNTRIES_PATH = WIKIDATA_V2_DIR / "modern_countries.json"


def _load_country_names(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {qid: val.get("name", "") for qid, val in load_json(path).items()}


def run(
    conn: duckdb.DuckDBPyConnection,
    json_path: Path = JSON_PATH,
    countries_path: Path = COUNTRIES_PATH,
) -> int:
    log("[DB] 02: Creating places table...")
    places = load_json(json_path)
    country_name = _load_country_names(countries_path)

    conn.execute("DROP TABLE IF EXISTS places")
    conn.execute(
        """
        CREATE TABLE places (
            id TEXT PRIMARY KEY,
            name_en TEXT,
            lat DOUBLE,
            lon DOUBLE,
            country_id TEXT,
            country_name TEXT,
            entity_type_ids TEXT,
            en_wikipedia_url TEXT
        )
        """
    )

    rows = []
    for qid, val in places.items():
        types = val.get("entity_types") or []
        cid = val.get("country")
        rows.append((
            qid,
            val.get("label"),
            val.get("lat"),
            val.get("lon"),
            cid,
            country_name.get(cid) if cid else None,
            ",".join(types) if types else None,
            val.get("en_wikipedia_url"),
        ))

    conn.executemany(
        "INSERT OR IGNORE INTO places "
        "(id, name_en, lat, lon, country_id, country_name, entity_type_ids, en_wikipedia_url) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_places_name ON places(name_en)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_places_country_id ON places(country_id)")

    log(f"[DB] 02: Inserted {len(rows)} places.")
    return len(rows)


def _sample_main() -> None:
    fake_places = {
        "Q90":   {"id": "Q90",  "label": "Paris",    "lat": 48.85, "lon":  2.35,
                  "country": "Q142", "entity_types": ["Q515"],
                  "en_wikipedia_url": "https://en.wikipedia.org/wiki/Paris"},
        "Q60":   {"id": "Q60",  "label": "New York", "lat": 40.71, "lon": -74.00,
                  "country": "Q30",  "entity_types": ["Q515", "Q1093829"]},
        "Q9999": {"id": "Q9999", "label": "Unknown"},
    }
    fake_countries = {
        "Q142": {"id": "Q142", "name": "France"},
        "Q30":  {"id": "Q30",  "name": "United States"},
    }
    with tempfile.TemporaryDirectory() as tmp:
        places_path = Path(tmp) / "place_metadata.json"
        places_path.write_text(__import__("json").dumps(fake_places))
        countries_path = Path(tmp) / "modern_countries.json"
        countries_path.write_text(__import__("json").dumps(fake_countries))
        sample_db = Path(tmp) / "sample.duckdb"
        with open_db(sample_db) as conn:
            n = run(conn, json_path=places_path, countries_path=countries_path)
            for row in conn.execute(
                "SELECT id, name_en, country_id, country_name, entity_type_ids "
                "FROM places ORDER BY id"
            ).fetchall():
                log(f"  places: {row}")
        log(f"[sample] inserted {n} places")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
