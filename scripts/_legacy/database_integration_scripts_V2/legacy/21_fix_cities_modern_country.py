"""21 — Replace `iso_a3` on cities with reverse-geocoded
`modern_country_name` + `iso_a3_code`.

Mirrors `enhance_db/src/bin/21_fix_cities_modern_country.rs`.

  Inputs : data/all_humans/city_modern_countries.json (city qid -> {country_name, iso_a3_code})
           cities (id, name_en, lat, lon, country_name, iso_a3)
  Output : cities recreated with modern_country_name + iso_a3_code (no iso_a3).
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from common import (
    ALL_HUMANS_DIR,
    DB_PATH,
    insert_rows,
    load_json,
    log,
    open_db,
    parse_run_mode,
    transaction,
)

JSON_PATH = ALL_HUMANS_DIR / "city_modern_countries.json"


def run(conn: sqlite3.Connection, json_path: Path = JSON_PATH) -> None:
    log("[DB] 21: Fix cities (add modern_country)...")
    geocoded = load_json(json_path)
    log(f"[21] Loaded {len(geocoded)} city geocoded entries")

    total = conn.execute("SELECT COUNT(*) FROM cities").fetchone()[0]
    log(f"[21] Total cities: {total}")

    rows = conn.execute(
        "SELECT id, name_en, lat, lon, country_name FROM cities ORDER BY rowid"
    ).fetchall()

    conn.execute("DROP TABLE IF EXISTS cities_new")
    conn.execute(
        """
        CREATE TABLE cities_new (
            id TEXT PRIMARY KEY,
            name_en TEXT,
            lat REAL,
            lon REAL,
            country_name TEXT,
            modern_country_name TEXT,
            iso_a3_code TEXT
        )
        """
    )

    mapped = 0
    unmapped = 0
    out = []
    for cid, name, lat, lon, country in rows:
        geo = geocoded.get(cid)
        if geo:
            cn = geo.get("country_name")
            iso = geo.get("iso_a3_code")
            if cn:
                mapped += 1
            else:
                unmapped += 1
        else:
            cn, iso = None, None
            unmapped += 1
        out.append((cid, name, lat, lon, country, cn, iso))

    with transaction(conn):
        conn.executemany(
            "INSERT INTO cities_new (id, name_en, lat, lon, country_name, "
            "modern_country_name, iso_a3_code) VALUES (?, ?, ?, ?, ?, ?, ?)",
            out,
        )

    conn.execute("DROP TABLE cities")
    conn.execute("ALTER TABLE cities_new RENAME TO cities")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cities_name ON cities(name_en)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cities_iso ON cities(iso_a3_code)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cities_modern_country ON cities(modern_country_name)"
    )
    conn.commit()
    log(f"[21] Mapped: {mapped}, Unmapped: {unmapped}")


def _sample_main() -> None:
    fake = {
        "Q90": {"country_name": "France", "iso_a3_code": "FRA"},
        "Q60": {"country_name": "United States", "iso_a3_code": "USA"},
    }
    with tempfile.TemporaryDirectory() as tmp:
        json_path = Path(tmp) / "city_modern_countries.json"
        json_path.write_text(json.dumps(fake))
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE cities (id TEXT PRIMARY KEY, name_en TEXT, lat REAL, lon REAL, "
                "country_name TEXT, iso_a3 TEXT)"
            )
            insert_rows(
                seed,
                "cities",
                [
                    {
                        "id": "Q90",
                        "name_en": "Paris",
                        "lat": 48.85,
                        "lon": 2.35,
                        "country_name": "Kingdom of France",
                        "iso_a3": None,
                    },
                    {
                        "id": "Q60",
                        "name_en": "New York",
                        "lat": 40.7,
                        "lon": -74.0,
                        "country_name": "United States",
                        "iso_a3": "USA",
                    },
                    {
                        "id": "Q1",
                        "name_en": "Atlantis",
                        "lat": None,
                        "lon": None,
                        "country_name": "Atlantis",
                        "iso_a3": None,
                    },
                ],
            )
        with open_db(db) as conn:
            run(conn, json_path=json_path)
            for row in conn.execute(
                "SELECT id, name_en, country_name, modern_country_name, iso_a3_code FROM cities ORDER BY id"
            ):
                log(f"  {row}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db(DB_PATH) as conn:
            run(conn)
    else:
        _sample_main()
