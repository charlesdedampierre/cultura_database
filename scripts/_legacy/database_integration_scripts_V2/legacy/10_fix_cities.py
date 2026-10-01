"""10 - Slim down cities and reorder by count DESC.

Mirrors `enhance_db/src/bin/10_fix_cities.rs`.

  Inputs : cities (any earlier shape with extra cols)
  Output : cities recreated with columns
            id, name_en, lat, lon, country_name, count
           rows physically ordered by count DESC, plus three indexes
           (idx_cities_name, idx_cities_count, idx_cities_country).

Usage
-----
    python3 10_fix_cities.py
    python3 10_fix_cities.py --full
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import (
    insert_rows,
    log,
    open_db,
    parse_run_mode,
)


def run(conn: sqlite3.Connection) -> None:
    log("=== Step 10: Reorder cities by count DESC ===")

    total = conn.execute("SELECT COUNT(*) FROM cities").fetchone()[0]
    log(f"[10] Cities table: {total} rows")
    if total:
        first = conn.execute("SELECT count FROM cities LIMIT 1").fetchone()[0]
        log(f"[10] Current first row count: {first}")

    log("[10] Removing iso_a3, country_id, continent_id, continent and reordering by count DESC...")
    conn.executescript(
        """
        DROP TABLE IF EXISTS cities_backup;
        ALTER TABLE cities RENAME TO cities_backup;

        CREATE TABLE cities (
            id TEXT PRIMARY KEY,
            name_en TEXT,
            lat REAL,
            lon REAL,
            country_name TEXT,
            count INTEGER DEFAULT 0
        );

        INSERT INTO cities (id, name_en, lat, lon, country_name, count)
        SELECT id, name_en, lat, lon, country_name, count
        FROM cities_backup
        ORDER BY count DESC;

        DROP TABLE cities_backup;
        """
    )
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_cities_name ON cities(name_en);
        CREATE INDEX IF NOT EXISTS idx_cities_count ON cities(count);
        CREATE INDEX IF NOT EXISTS idx_cities_country ON cities(country_name);
        """
    )
    conn.commit()

    if total:
        new_first = conn.execute("SELECT count FROM cities LIMIT 1").fetchone()[0]
        log(f"[10] New first row count: {new_first} (should be highest)")

    rows = conn.execute("SELECT name_en, count FROM cities LIMIT 5").fetchall()
    for name, count in rows:
        log(f"[10]   {name} ({count})")
    log("=== Step 10 complete ===")


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db_path) as seed:
            seed.execute(
                "CREATE TABLE cities ("
                "id TEXT PRIMARY KEY, name_en TEXT, lat REAL, lon REAL, "
                "country_name TEXT, count INTEGER, "
                "iso_a3 TEXT, country_id TEXT, continent_id TEXT, continent TEXT)"
            )
            insert_rows(seed, "cities", [
                {"id": "Q90", "name_en": "Paris", "lat": 48.85, "lon": 2.35,
                 "country_name": "France", "count": 100,
                 "iso_a3": "FRA", "country_id": "Q142", "continent_id": "Q46", "continent": "Europe"},
                {"id": "Q60", "name_en": "New York", "lat": 40.71, "lon": -74.01,
                 "country_name": "United States", "count": 500,
                 "iso_a3": "USA", "country_id": "Q30", "continent_id": "Q49", "continent": "North America"},
                {"id": "Q1490", "name_en": "Tokyo", "lat": 35.68, "lon": 139.69,
                 "country_name": "Japan", "count": 250,
                 "iso_a3": "JPN", "country_id": "Q17", "continent_id": "Q48", "continent": "Asia"},
            ])
            seed.commit()

        with open_db(db_path) as conn:
            run(conn)
            rows = conn.execute(
                "SELECT name_en, count, country_name FROM cities ORDER BY count DESC"
            ).fetchall()
            cols = [r[1] for r in conn.execute("PRAGMA table_info(cities)").fetchall()]
        log(f"[sample] cities columns: {cols}")
        for r in rows:
            log(f"  cities: {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
