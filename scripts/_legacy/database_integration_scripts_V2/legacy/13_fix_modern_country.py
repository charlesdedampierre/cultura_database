"""13 - Recompute modern_country count and reorder by count DESC.

Mirrors `enhance_db/src/bin/13_fix_modern_country.rs`.

  Inputs : modern_country, nationalities (modern_country_name, count)
  Output : modern_country.count = SUM(nationalities.count)
           grouped by modern_country.name; table rebuilt ordered by
           count DESC.

Usage
-----
    python3 13_fix_modern_country.py
    python3 13_fix_modern_country.py --full
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import insert_rows, log, open_db, parse_run_mode


def run(conn: sqlite3.Connection) -> None:
    log("=== Step 13: Fix modern_country count and order ===")

    log("[13] Computing modern_country counts from nationalities...")
    conn.execute(
        """
        UPDATE modern_country SET count = COALESCE(
            (SELECT SUM(count) FROM nationalities
             WHERE modern_country_name = modern_country.name), 0
        )
        """
    )
    conn.commit()

    nonzero = conn.execute(
        "SELECT COUNT(*) FROM modern_country WHERE count > 0"
    ).fetchone()[0]
    log(f"[13]   {nonzero} modern countries with non-zero count")

    log("[13] Reordering modern_country by count DESC...")
    conn.executescript(
        """
        DROP TABLE IF EXISTS modern_country_backup;
        ALTER TABLE modern_country RENAME TO modern_country_backup;

        CREATE TABLE modern_country (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            continent TEXT,
            iso_a3_code TEXT NOT NULL,
            en_wikipedia_url TEXT,
            count INTEGER DEFAULT 0
        );

        INSERT INTO modern_country (id, name, continent, iso_a3_code, en_wikipedia_url, count)
        SELECT id, name, continent, iso_a3_code, en_wikipedia_url, count
        FROM modern_country_backup
        ORDER BY count DESC;

        DROP TABLE modern_country_backup;
        """
    )
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM modern_country").fetchone()[0]
    log(f"[13] modern_country: {total} rows")
    rows = conn.execute("SELECT name, count FROM modern_country LIMIT 10").fetchall()
    for name, count in rows:
        log(f"[13]   {name} ({count})")
    log("=== Step 13 complete ===")


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db_path) as seed:
            seed.execute(
                "CREATE TABLE modern_country ("
                "id TEXT PRIMARY KEY, name TEXT NOT NULL, continent TEXT, "
                "iso_a3_code TEXT NOT NULL, en_wikipedia_url TEXT, count INTEGER DEFAULT 0)"
            )
            seed.execute(
                "CREATE TABLE nationalities ("
                "wikidata_id TEXT PRIMARY KEY, name_en TEXT, count INTEGER, "
                "modern_country_name TEXT)"
            )
            insert_rows(seed, "modern_country", [
                {"id": "Q142", "name": "France", "continent": "Europe",
                 "iso_a3_code": "FRA", "en_wikipedia_url": None, "count": 0},
                {"id": "Q30", "name": "United States", "continent": "North America",
                 "iso_a3_code": "USA", "en_wikipedia_url": None, "count": 0},
                {"id": "Q145", "name": "United Kingdom", "continent": "Europe",
                 "iso_a3_code": "GBR", "en_wikipedia_url": None, "count": 0},
            ])
            insert_rows(seed, "nationalities", [
                {"wikidata_id": "Q142", "name_en": "French", "count": 100, "modern_country_name": "France"},
                {"wikidata_id": "Q30", "name_en": "American", "count": 500, "modern_country_name": "United States"},
                {"wikidata_id": "Q145", "name_en": "English", "count": 200, "modern_country_name": "United Kingdom"},
                {"wikidata_id": "Q145b", "name_en": "Scottish", "count": 50, "modern_country_name": "United Kingdom"},
            ])
            seed.commit()

        with open_db(db_path) as conn:
            run(conn)
            rows = conn.execute("SELECT name, count FROM modern_country").fetchall()
        for r in rows:
            log(f"  modern_country: {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
