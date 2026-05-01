"""06 - Restructure the nationalities table.

Mirrors `enhance_db/src/bin/06_restructure_nationalities.rs`.

  Inputs : data/all_humans/nationality_sitelinks.json   {qid: en_url}
           data/all_humans/nationality_locations.json   {qid: {lat, lon}}
           data/all_humans/nationality_countries.json   {qid: {country_name}}
           nationalities (existing rows)
  Output : nationalities (rebuilt) with wikidata_id PK first, plus
           en_wikipedia_url, lat/lon, modern_country_name columns and
           two indexes.

Usage
-----
    python3 06_restructure_nationalities.py
    python3 06_restructure_nationalities.py --full
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from common import (
    ALL_HUMANS_DIR,
    insert_rows,
    load_json,
    log,
    open_db,
    parse_run_mode,
)

SITELINKS_PATH = ALL_HUMANS_DIR / "nationality_sitelinks.json"
LOCATIONS_PATH = ALL_HUMANS_DIR / "nationality_locations.json"
NAT_COUNTRIES_PATH = ALL_HUMANS_DIR / "nationality_countries.json"


def run(
    conn: sqlite3.Connection,
    sitelinks_path: Path = SITELINKS_PATH,
    locations_path: Path = LOCATIONS_PATH,
    nat_countries_path: Path = NAT_COUNTRIES_PATH,
) -> int:
    log("[DB] 06: Restructuring nationalities table...")

    sitelinks = load_json(sitelinks_path)
    log(f"[DB] Loaded {len(sitelinks)} nationality sitelinks")
    locations = load_json(locations_path)
    log(f"[DB] Loaded {len(locations)} nationality locations")
    nat_countries = load_json(nat_countries_path)
    log(f"[DB] Loaded {len(nat_countries)} nationality->country mappings")

    existing = conn.execute(
        "SELECT name_en, count, wikidata_id, description_en, instance_of FROM nationalities"
    ).fetchall()
    log(f"[DB] Read {len(existing)} existing nationalities")

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
            modern_country_name TEXT
        )
        """
    )

    insert_sql = (
        "INSERT OR IGNORE INTO nationalities "
        "(wikidata_id, name_en, count, description_en, instance_of, "
        "en_wikipedia_url, lat, lon, modern_country_name) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    rows: list[tuple] = []
    for name_en, count, wid, description, instance_of in existing:
        wid = wid or ""
        wiki_url = sitelinks.get(wid)
        if isinstance(wiki_url, dict):
            wiki_url = wiki_url.get("url") or wiki_url.get("en")
        loc = locations.get(wid) or {}
        lat = loc.get("lat") if isinstance(loc, dict) else None
        lon = loc.get("lon") if isinstance(loc, dict) else None
        nat = nat_countries.get(wid) or {}
        modern_country = nat.get("country_name") if isinstance(nat, dict) else None
        rows.append((wid, name_en, count, description, instance_of,
                     wiki_url, lat, lon, modern_country))

    try:
        from tqdm import tqdm
        rows_iter = tqdm(rows, desc="Inserting nationalities", unit="row")
    except ImportError:
        rows_iter = rows
    conn.executemany(insert_sql, rows_iter)
    conn.commit()

    conn.execute("DROP TABLE IF EXISTS nationalities_backup")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nationalities_name ON nationalities(name_en)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nationalities_country ON nationalities(modern_country_name)")
    conn.commit()

    log("[DB] 06: Done. Nationalities restructured.")
    return len(rows)


def _sample_main() -> None:
    fake_sitelinks = {"Q142": "https://en.wikipedia.org/wiki/France"}
    fake_locations = {"Q142": {"lat": 46.0, "lon": 2.0}}
    fake_countries = {"Q142": {"country_name": "France"}}

    with tempfile.TemporaryDirectory() as tmp:
        sl_path = Path(tmp) / "sl.json"
        loc_path = Path(tmp) / "loc.json"
        ncp_path = Path(tmp) / "ncp.json"
        sl_path.write_text(json.dumps(fake_sitelinks))
        loc_path.write_text(json.dumps(fake_locations))
        ncp_path.write_text(json.dumps(fake_countries))

        db_path = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db_path) as seed:
            seed.execute(
                "CREATE TABLE nationalities ("
                "name_en TEXT PRIMARY KEY, count INTEGER, wikidata_id TEXT, "
                "description_en TEXT, instance_of TEXT)"
            )
            insert_rows(seed, "nationalities", [
                {"name_en": "French", "count": 1234, "wikidata_id": "Q142",
                 "description_en": "from France", "instance_of": "country"},
                {"name_en": "Atlantean", "count": 0, "wikidata_id": "Q999",
                 "description_en": None, "instance_of": None},
            ])
            seed.commit()

        with open_db(db_path) as conn:
            n = run(conn, sl_path, loc_path, ncp_path)
            rows = conn.execute(
                "SELECT wikidata_id, name_en, count, en_wikipedia_url, lat, lon, modern_country_name "
                "FROM nationalities ORDER BY count DESC"
            ).fetchall()
        log(f"[sample] inserted {n} nationalities")
        for r in rows:
            log(f"  nationalities: {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
