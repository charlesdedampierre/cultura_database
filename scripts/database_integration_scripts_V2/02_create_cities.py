"""02 — Create the `cities` reference table from v2 place metadata.

Inputs : data/all_humans/wikidata_extraction_scripts_v2/place_metadata.json
         (one entry per place QID used as a P19 / P20 of any Q5 human)
Output : cities (id PK, name_en, lat, lon, country_id, country_name,
                 entity_type_ids, en_wikipedia_url)

`country_name` is filled in by 01 (modern_country) when that script runs
after this one — but 01 already runs first in `build_all.py` and
back-fills idempotently via UPDATE...JOIN, so order doesn't matter.

Usage
-----
    python3 02_create_cities.py            # tiny synthetic JSON
    python3 02_create_cities.py --full     # data/humans_v2.sqlite3
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import (
    WIKIDATA_V2_DIR,
    log,
    load_json,
    open_db,
    parse_run_mode,
)


JSON_PATH = WIKIDATA_V2_DIR / "place_metadata.json"


def run(conn: sqlite3.Connection, json_path: Path = JSON_PATH) -> int:
    log("[DB] 02: Creating cities table...")
    places = load_json(json_path)

    conn.execute("DROP TABLE IF EXISTS cities")
    conn.execute(
        """
        CREATE TABLE cities (
            id TEXT PRIMARY KEY,
            name_en TEXT,
            lat REAL,
            lon REAL,
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
        rows.append((
            qid,
            val.get("label"),
            val.get("lat"),
            val.get("lon"),
            val.get("country"),
            None,  # filled in by modern_country join below
            ",".join(types) if types else None,
            val.get("en_wikipedia_url"),
        ))

    conn.executemany(
        "INSERT OR IGNORE INTO cities "
        "(id, name_en, lat, lon, country_id, country_name, entity_type_ids, en_wikipedia_url) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()

    # Backfill country_name from modern_country if it exists.
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='modern_country'"
    ).fetchone():
        conn.execute(
            """
            UPDATE cities SET country_name = (
                SELECT name FROM modern_country WHERE modern_country.id = cities.country_id
            )
            WHERE country_id IN (SELECT id FROM modern_country)
            """
        )
        conn.commit()

    conn.execute("CREATE INDEX IF NOT EXISTS idx_cities_name ON cities(name_en)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cities_country ON cities(country_id)")
    conn.commit()

    log(f"[DB] 02: Inserted {len(rows)} cities.")
    return len(rows)


def _sample_main() -> None:
    fake = {
        "Q90":   {"id": "Q90",  "label": "Paris",    "lat": 48.85, "lon":  2.35,
                  "country": "Q142", "entity_types": ["Q515"],
                  "en_wikipedia_url": "https://en.wikipedia.org/wiki/Paris"},
        "Q60":   {"id": "Q60",  "label": "New York", "lat": 40.71, "lon": -74.00,
                  "country": "Q30",  "entity_types": ["Q515", "Q1093829"]},
        "Q9999": {"id": "Q9999", "label": "Unknown"},  # missing coords/country
    }
    with tempfile.TemporaryDirectory() as tmp:
        json_path = Path(tmp) / "place_metadata.json"
        json_path.write_text(__import__("json").dumps(fake))
        sample_db = Path(tmp) / "sample.sqlite3"
        with open_db(sample_db) as conn:
            n = run(conn, json_path=json_path)
            for row in conn.execute(
                "SELECT id, name_en, country_id, country_name, entity_type_ids "
                "FROM cities ORDER BY id"
            ):
                log(f"  cities: {row}")
        log(f"[sample] inserted {n} cities")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
