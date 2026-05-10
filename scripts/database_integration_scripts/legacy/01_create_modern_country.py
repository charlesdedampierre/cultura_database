"""01 — Create the `modern_country` reference table.

Mirrors `enhance_db/src/bin/01_create_modern_country.rs`.

  Inputs : data/all_humans/modern_countries.json   (qid -> country dict)
           cities                                    (only its `country_id`
                                                     and `count` columns)
  Output : modern_country (id PK, name, continent, iso_a3_code,
                            en_wikipedia_url, count)
           cities.country_name updated to match modern_country.name
           Two indexes on iso_a3_code and name.

Usage
-----
    python3 01_create_modern_country.py            # try on a tiny synthetic DB
    python3 01_create_modern_country.py --full     # run on data/humans_clean.sqlite3
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from common import (
    WIKIDATA_V2_DIR,
    add_column_if_missing,
    insert_rows,
    log,
    load_json,
    open_db,
    parse_run_mode,
    table_exists,
)

JSON_PATH = WIKIDATA_V2_DIR / "modern_countries.json"


def run(conn: sqlite3.Connection, json_path: Path = JSON_PATH) -> int:
    log("[DB] 01: Creating modern_country table...")

    countries = load_json(json_path)

    conn.execute("DROP TABLE IF EXISTS modern_country")
    conn.execute(
        """
        CREATE TABLE modern_country (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            continent TEXT,
            iso_a3_code TEXT NOT NULL,
            en_wikipedia_url TEXT,
            count INTEGER DEFAULT 0
        )
        """
    )

    rows = []
    for _qid, val in countries.items():
        iso3 = val.get("iso_a3_code") or ""
        if not iso3:
            continue
        rows.append(
            (
                val.get("id", ""),
                val.get("name", ""),
                val.get("continent"),
                iso3,
                val.get("en_wikipedia_url"),
            )
        )

    conn.executemany(
        "INSERT OR IGNORE INTO modern_country "
        "(id, name, continent, iso_a3_code, en_wikipedia_url) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    inserted = len(rows)
    conn.commit()
    log(f"[DB] Inserted {inserted} modern countries.")

    if table_exists(conn, "cities"):
        cols = {r[1] for r in conn.execute("PRAGMA table_info(cities)").fetchall()}
        if "country_id" in cols:
            add_column_if_missing(conn, "cities", "country_name", "TEXT")
            updated = conn.execute(
                """
                UPDATE cities SET country_name = (
                    SELECT modern_country.name
                    FROM modern_country
                    WHERE modern_country.id = cities.country_id
                )
                WHERE country_id IN (SELECT id FROM modern_country)
                """
            ).rowcount
            log(f"[DB] Updated {updated} city rows with modern_country_name.")

        if "count" in cols:
            conn.execute(
                """
                UPDATE modern_country SET count = COALESCE(
                    (SELECT SUM(cities.count) FROM cities
                     WHERE cities.country_id = modern_country.id),
                    0
                )
                """
            )
            conn.commit()

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_modern_country_iso3 "
        "ON modern_country(iso_a3_code)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_modern_country_name "
        "ON modern_country(name)"
    )
    conn.commit()
    log("[DB] 01: Done.")
    return inserted


def _sample_main() -> None:
    """Build a tiny synthetic SQLite to exercise the script end-to-end."""
    fake_countries = {
        "Q142": {
            "id": "Q142", "name": "France", "iso_a3_code": "FRA",
            "continent_id": "Q46", "continent": "Europe",
            "en_wikipedia_url": "https://en.wikipedia.org/wiki/France",
        },
        "Q30": {
            "id": "Q30", "name": "United States", "iso_a3_code": "USA",
            "continent_id": "Q49", "continent": "North America",
            "en_wikipedia_url": "https://en.wikipedia.org/wiki/United_States",
        },
        "Q34": {  # missing iso_a3_code -> should be skipped
            "id": "Q34", "name": "Sweden", "iso_a3_code": "",
            "continent": "Europe",
        },
    }

    with tempfile.TemporaryDirectory() as tmp:
        json_path = Path(tmp) / "modern_countries.json"
        json_path.write_text(json.dumps(fake_countries))
        sample_db = Path(tmp) / "sample.sqlite3"

        with sqlite3.connect(sample_db) as seed:
            seed.execute(
                "CREATE TABLE cities (id TEXT PRIMARY KEY, name_en TEXT, "
                "country_id TEXT, country_name TEXT, count INTEGER)"
            )
            insert_rows(seed, "cities", [
                {"id": "Q90",  "name_en": "Paris",  "country_id": "Q142", "country_name": None, "count": 100},
                {"id": "Q60",  "name_en": "New York","country_id": "Q30", "country_name": None, "count": 200},
                {"id": "Q100", "name_en": "Boston", "country_id": "Q30", "country_name": None, "count":  30},
            ])

        with open_db(sample_db) as conn:
            n = run(conn, json_path=json_path)
            mc = conn.execute(
                "SELECT id, name, iso_a3_code, count FROM modern_country "
                "ORDER BY count DESC"
            ).fetchall()
            cities = conn.execute(
                "SELECT id, name_en, country_id, country_name FROM cities"
            ).fetchall()

        log(f"[sample] inserted {n} countries")
        for row in mc:
            log(f"  modern_country: {row}")
        for row in cities:
            log(f"  cities:         {row}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
