"""43 - Create individuals_regions (country -> region/macro_region by year).

Mirrors `enhance_db/src/bin/43_create_individuals_regions.rs`.

  Inputs : individuals_countries (wikidata_id, name_en, iso_country_name,
           iso_a3_code, origins), regions (macro_region, region, iso_a3,
           start_year, end_year), individuals_impact_date.
  Output : individuals_regions (wikidata_id PK, name_en, iso_country_name,
           iso_a3_code, origins, region, macro_region, impact_year) + 5 indexes.

Usage
-----
    python3 43_create_individuals_regions.py            # synthetic
    python3 43_create_individuals_regions.py --full     # real DB
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from tqdm import tqdm

from common import insert_rows, log, open_db, parse_run_mode, parse_year

BATCH_SIZE = 50_000


def run(conn: sqlite3.Connection) -> int:
    log("[DB] 43: Creating individuals_regions...")

    region_lookup: dict[str, list[tuple]] = {}
    for macro, region, iso, start, end in conn.execute(
        "SELECT macro_region, region, iso_a3, start_year, end_year FROM regions"
    ):
        region_lookup.setdefault(iso, []).append((macro, region, start, end))

    impact: dict[str, int] = {}
    for wid, ds in conn.execute(
        "SELECT wikidata_id, impact_date FROM individuals_impact_date"
    ):
        y = parse_year(ds)
        if y is not None:
            impact[wid] = y

    conn.execute("DROP TABLE IF EXISTS individuals_regions")
    conn.execute(
        """
        CREATE TABLE individuals_regions (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            iso_country_name TEXT,
            iso_a3_code TEXT,
            origins TEXT,
            region TEXT,
            macro_region TEXT,
            impact_year INTEGER
        )
        """
    )
    total = conn.execute("SELECT COUNT(*) FROM individuals_countries").fetchone()[0]
    cursor = conn.execute(
        "SELECT wikidata_id, name_en, iso_country_name, iso_a3_code, origins "
        "FROM individuals_countries ORDER BY rowid"
    )
    sql = (
        "INSERT OR IGNORE INTO individuals_regions "
        "(wikidata_id, name_en, iso_country_name, iso_a3_code, origins, region, macro_region, impact_year) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    )
    inserted = 0
    buf: list[tuple] = []
    for wid, name_en, country, iso, origins in tqdm(cursor, total=total, desc="43_regions"):
        year = impact.get(wid)
        if year is None:
            continue
        entries = region_lookup.get(iso)
        if not entries:
            continue
        regions, macros = [], []
        for macro, region, start, end in entries:
            if year < start:
                continue
            if end is not None and year > end:
                continue
            if region not in regions:
                regions.append(region)
            if macro not in macros:
                macros.append(macro)
        if not regions:
            continue
        buf.append((wid, name_en, country, iso, origins,
                    "; ".join(regions), "; ".join(macros), year))
        if len(buf) >= BATCH_SIZE:
            conn.executemany(sql, buf)
            conn.commit()
            inserted += len(buf)
            buf.clear()
    if buf:
        conn.executemany(sql, buf)
        conn.commit()
        inserted += len(buf)

    for ddl in (
        "CREATE INDEX IF NOT EXISTS idx_indregions_region ON individuals_regions(region)",
        "CREATE INDEX IF NOT EXISTS idx_indregions_macro_region ON individuals_regions(macro_region)",
        "CREATE INDEX IF NOT EXISTS idx_indregions_iso ON individuals_regions(iso_a3_code)",
        "CREATE INDEX IF NOT EXISTS idx_indregions_country ON individuals_regions(iso_country_name)",
        "CREATE INDEX IF NOT EXISTS idx_indregions_year ON individuals_regions(impact_year)",
    ):
        conn.execute(ddl)
    conn.commit()
    log(f"[43] inserted {inserted}")
    return inserted


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.executescript(
                """
                CREATE TABLE individuals_countries (wikidata_id TEXT PRIMARY KEY, name_en TEXT,
                    iso_country_name TEXT, iso_a3_code TEXT, origins TEXT);
                CREATE TABLE regions (macro_region TEXT, region TEXT, iso_a3 TEXT,
                    start_year INTEGER, end_year INTEGER);
                CREATE TABLE individuals_impact_date (wikidata_id TEXT, impact_date TEXT);
                """
            )
            insert_rows(seed, "individuals_countries", [
                {"wikidata_id": "Q1", "name_en": "Alice", "iso_country_name": "France",
                 "iso_a3_code": "FRA", "origins": "nationality"},
                {"wikidata_id": "Q2", "name_en": "Bob", "iso_country_name": "France",
                 "iso_a3_code": "FRA", "origins": "deathplace"},
                {"wikidata_id": "Q3", "name_en": "Cleo", "iso_country_name": "Egypt",
                 "iso_a3_code": "EGY", "origins": "nationality"},
            ])
            insert_rows(seed, "regions", [
                {"macro_region": "Europe", "region": "Western Europe", "iso_a3": "FRA",
                 "start_year": 1500, "end_year": 2100},
                {"macro_region": "Africa", "region": "North Africa", "iso_a3": "EGY",
                 "start_year": -3000, "end_year": 100},
            ])
            insert_rows(seed, "individuals_impact_date", [
                {"wikidata_id": "Q1", "impact_date": "1850"},
                {"wikidata_id": "Q2", "impact_date": "1700"},
                {"wikidata_id": "Q3", "impact_date": "-50"},
            ])
        with open_db(db) as conn:
            n = run(conn)
            rows = conn.execute(
                "SELECT wikidata_id, region, macro_region, impact_year FROM individuals_regions"
            ).fetchall()
        log(f"[sample] {n} rows")
        for r in rows:
            log(f"  {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
