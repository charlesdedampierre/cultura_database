"""18 — Replace `modern_country_name` on `nationalities` with reverse-geocoded
`country_name` + `iso_a3_code`.

Mirrors `enhance_db/src/bin/18_fix_nationalities.rs`.

  Inputs : data/all_humans/nationality_modern_countries.json
           nationalities (existing schema with modern_country_name)
  Output : nationalities recreated with country_name + iso_a3_code
           Indexes on name_en, country_name, iso_a3_code.
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
)

JSON_PATH = ALL_HUMANS_DIR / "nationality_modern_countries.json"


def run(conn: sqlite3.Connection, json_path: Path = JSON_PATH) -> None:
    log("[DB] 18: Fix nationalities (replace modern_country_name)...")

    geocoded = load_json(json_path)
    log(f"[18] Loaded {len(geocoded)} geocoded entries")

    rows = conn.execute(
        "SELECT wikidata_id, name_en, count, description_en, instance_of, "
        "en_wikipedia_url, lat, lon FROM nationalities"
    ).fetchall()
    log(f"[18] Read {len(rows)} nationalities")

    conn.execute("DROP TABLE IF EXISTS nationalities_backup")
    conn.execute("ALTER TABLE nationalities RENAME TO nationalities_backup")
    conn.execute(
        """
        CREATE TABLE nationalities (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            count INTEGER DEFAULT 0,
            description_en TEXT,
            instance_of TEXT,
            en_wikipedia_url TEXT,
            lat REAL,
            lon REAL,
            country_name TEXT,
            iso_a3_code TEXT
        )
        """
    )

    mapped = 0
    unmapped = 0
    out_rows = []
    for wid, name_en, count, desc, inst, wiki, lat, lon in rows:
        geo = geocoded.get(wid)
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
        out_rows.append((wid, name_en, count, desc, inst, wiki, lat, lon, cn, iso))

    conn.executemany(
        "INSERT INTO nationalities (wikidata_id, name_en, count, description_en, "
        "instance_of, en_wikipedia_url, lat, lon, country_name, iso_a3_code) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        out_rows,
    )
    conn.execute("DROP TABLE IF EXISTS nationalities_backup")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nationalities_name ON nationalities(name_en)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nationalities_country ON nationalities(country_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nationalities_iso ON nationalities(iso_a3_code)")
    conn.commit()
    log(f"[18] Mapped: {mapped}, Unmapped: {unmapped}")


def _sample_main() -> None:
    fake = {
        "Q142": {"country_name": "France", "iso_a3_code": "FRA"},
        "Q183": {"country_name": "Germany", "iso_a3_code": "DEU"},
    }
    with tempfile.TemporaryDirectory() as tmp:
        json_path = Path(tmp) / "nationality_modern_countries.json"
        json_path.write_text(json.dumps(fake))
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                """
                CREATE TABLE nationalities (
                    wikidata_id TEXT PRIMARY KEY, name_en TEXT, count INTEGER,
                    description_en TEXT, instance_of TEXT, en_wikipedia_url TEXT,
                    lat REAL, lon REAL, modern_country_name TEXT
                )
                """
            )
            insert_rows(seed, "nationalities", [
                {"wikidata_id": "Q142", "name_en": "French", "count": 1000, "description_en": None,
                 "instance_of": None, "en_wikipedia_url": None, "lat": 46.0, "lon": 2.0,
                 "modern_country_name": "France"},
                {"wikidata_id": "Q183", "name_en": "German", "count": 800, "description_en": None,
                 "instance_of": None, "en_wikipedia_url": None, "lat": 51.0, "lon": 10.0,
                 "modern_country_name": "Germany"},
                {"wikidata_id": "Q9999", "name_en": "Unknown", "count": 1, "description_en": None,
                 "instance_of": None, "en_wikipedia_url": None, "lat": None, "lon": None,
                 "modern_country_name": None},
            ])

        with open_db(db) as conn:
            run(conn, json_path=json_path)
            for row in conn.execute(
                "SELECT wikidata_id, name_en, country_name, iso_a3_code FROM nationalities"
            ):
                log(f"  {row}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db(DB_PATH) as conn:
            run(conn)
    else:
        _sample_main()
