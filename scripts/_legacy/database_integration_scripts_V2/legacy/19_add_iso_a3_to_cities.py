"""19 — Add `iso_a3` to `cities`, populated by joining `country_name` to
`modern_country.name`.

Mirrors `enhance_db/src/bin/19_add_iso_a3_to_cities.rs`.

  Inputs : cities (must already have country_name), modern_country
  Output : cities.iso_a3 populated; index idx_cities_iso_a3
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import (
    DB_PATH,
    column_exists,
    insert_rows,
    log,
    open_db,
    parse_run_mode,
)


def run(conn: sqlite3.Connection) -> None:
    log("[DB] 19: Add iso_a3 to cities...")

    if column_exists(conn, "cities", "iso_a3"):
        log("[19] iso_a3 column already exists, recreating without it first...")
        conn.executescript(
            """
            CREATE TABLE cities_temp AS SELECT id, name_en, lat, lon, country_name FROM cities;
            DROP TABLE cities;
            ALTER TABLE cities_temp RENAME TO cities;
            """
        )

    conn.execute("ALTER TABLE cities ADD COLUMN iso_a3 TEXT")

    updated = conn.execute(
        """
        UPDATE cities SET iso_a3 = (
            SELECT mc.iso_a3_code FROM modern_country mc
            WHERE mc.name = cities.country_name LIMIT 1
        ) WHERE country_name IS NOT NULL
        """
    ).rowcount
    conn.commit()
    log(f"[19] Updated {updated} cities with iso_a3")

    total = conn.execute("SELECT COUNT(*) FROM cities").fetchone()[0]
    with_iso = conn.execute(
        "SELECT COUNT(*) FROM cities WHERE iso_a3 IS NOT NULL"
    ).fetchone()[0]
    without_iso = conn.execute(
        "SELECT COUNT(*) FROM cities WHERE iso_a3 IS NULL AND country_name IS NOT NULL"
    ).fetchone()[0]
    log(f"[19] Total: {total}, with iso_a3: {with_iso}, missing: {without_iso}")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_cities_iso_a3 ON cities(iso_a3)")
    conn.commit()


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE cities (id TEXT PRIMARY KEY, name_en TEXT, "
                "lat REAL, lon REAL, country_name TEXT)"
            )
            seed.execute(
                "CREATE TABLE modern_country (id TEXT PRIMARY KEY, name TEXT, iso_a3_code TEXT)"
            )
            insert_rows(seed, "modern_country", [
                {"id": "Q142", "name": "France", "iso_a3_code": "FRA"},
                {"id": "Q30", "name": "United States", "iso_a3_code": "USA"},
            ])
            insert_rows(seed, "cities", [
                {"id": "Q90", "name_en": "Paris", "lat": 48.85, "lon": 2.35, "country_name": "France"},
                {"id": "Q60", "name_en": "New York", "lat": 40.7, "lon": -74.0, "country_name": "United States"},
                {"id": "Q1", "name_en": "Atlantis", "lat": None, "lon": None, "country_name": "Atlantis"},
            ])

        with open_db(db) as conn:
            run(conn)
            for row in conn.execute(
                "SELECT id, name_en, country_name, iso_a3 FROM cities ORDER BY id"
            ):
                log(f"  {row}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db(DB_PATH) as conn:
            run(conn)
    else:
        _sample_main()
