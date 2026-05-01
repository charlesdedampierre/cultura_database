"""31 - Rebuild the corrupted individuals_countries table.

Mirrors `enhance_db/src/bin/31_rebuild_individuals_countries.rs`.

  Inputs : individuals (wikidata_id, name_en, nationalities_en,
                         deathcity_en, birthcity_en)
           nationalities (name_en, iso_country_name, iso_a3_code)
           cities (name_en, iso_country_name, iso_a3_code)
           regions (macro_region, region, iso_a3, start_year, end_year)
           individuals_impact_date (wikidata_id, impact_date)
  Output : individuals_countries (wikidata_id PK, name_en, iso_country_name,
                                   iso_a3_code, origins, region, macro_region)
           plus 5 indexes.

Usage
-----
    python3 31_rebuild_individuals_countries.py            # synthetic DB
    python3 31_rebuild_individuals_countries.py --full     # real DB
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from tqdm import tqdm

from common import (
    DB_PATH,
    insert_rows,
    log,
    open_db,
    parse_run_mode,
    parse_year,
)

BATCH_SIZE = 50_000


def _resolve_country(nat_lookup, city_lookup, nats_en, deathcity, birthcity):
    if nats_en:
        for nat in nats_en.split("; "):
            hit = nat_lookup.get(nat.strip())
            if hit:
                return (*hit, "nationality")
    if deathcity:
        hit = city_lookup.get(deathcity.strip())
        if hit:
            return (*hit, "deathplace")
    if birthcity:
        hit = city_lookup.get(birthcity.strip())
        if hit:
            return (*hit, "birthplace")
    return None


def _resolve_region(region_lookup, iso_a3, year):
    entries = region_lookup.get(iso_a3)
    if not entries or year is None:
        return None, None
    regions, macro_regions = [], []
    for macro, region, start, end in entries:
        if year < start:
            continue
        if end is not None and year > end:
            continue
        if region not in regions:
            regions.append(region)
        if macro not in macro_regions:
            macro_regions.append(macro)
    if not regions:
        return None, None
    return "; ".join(regions), "; ".join(macro_regions)


def run(conn: sqlite3.Connection) -> int:
    log("[DB] 31: Rebuilding individuals_countries...")

    nat_lookup = {}
    for name, country, iso in conn.execute(
        "SELECT name_en, iso_country_name, iso_a3_code FROM nationalities "
        "WHERE iso_country_name IS NOT NULL AND iso_a3_code IS NOT NULL"
    ):
        nat_lookup.setdefault(name, (country, iso))
    log(f"[31] Nationality lookup: {len(nat_lookup)} entries")

    city_lookup = {}
    for name, country, iso in conn.execute(
        "SELECT name_en, iso_country_name, iso_a3_code FROM cities "
        "WHERE iso_country_name IS NOT NULL AND iso_a3_code IS NOT NULL"
    ):
        city_lookup.setdefault(name, (country, iso))
    log(f"[31] City lookup: {len(city_lookup)} entries")

    region_lookup: dict[str, list[tuple]] = {}
    for macro, region, iso, start, end in conn.execute(
        "SELECT macro_region, region, iso_a3, start_year, end_year FROM regions"
    ):
        region_lookup.setdefault(iso, []).append((macro, region, start, end))
    log(f"[31] Region lookup: {len(region_lookup)} ISO codes")

    impact_lookup: dict[str, int] = {}
    for wid, date_str in conn.execute(
        "SELECT wikidata_id, impact_date FROM individuals_impact_date"
    ):
        y = parse_year(date_str)
        if y is not None:
            impact_lookup[wid] = y
    log(f"[31] Impact date lookup: {len(impact_lookup)} entries")

    conn.execute("DROP TABLE IF EXISTS individuals_countries")
    conn.execute(
        """
        CREATE TABLE individuals_countries (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            iso_country_name TEXT,
            iso_a3_code TEXT,
            origins TEXT,
            region TEXT,
            macro_region TEXT
        )
        """
    )

    total = conn.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]
    log(f"[31] Total individuals to process: {total}")

    cursor = conn.execute(
        "SELECT wikidata_id, name_en, nationalities_en, deathcity_en, birthcity_en "
        "FROM individuals ORDER BY rowid"
    )

    inserted = 0
    buf: list[tuple] = []
    sql = (
        "INSERT OR IGNORE INTO individuals_countries "
        "(wikidata_id, name_en, iso_country_name, iso_a3_code, origins, region, macro_region) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)"
    )
    for wid, name_en, nats, dc, bc in tqdm(cursor, total=total, desc="indiv_countries", unit="row"):
        hit = _resolve_country(nat_lookup, city_lookup, nats, dc, bc)
        if hit is None:
            continue
        country, iso, origin = hit
        year = impact_lookup.get(wid)
        region, macro = _resolve_region(region_lookup, iso, year)
        buf.append((wid, name_en, country, iso, origin, region, macro))
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
        "CREATE INDEX IF NOT EXISTS idx_indcountries_country ON individuals_countries(iso_country_name)",
        "CREATE INDEX IF NOT EXISTS idx_indcountries_iso ON individuals_countries(iso_a3_code)",
        "CREATE INDEX IF NOT EXISTS idx_indcountries_origins ON individuals_countries(origins)",
        "CREATE INDEX IF NOT EXISTS idx_indcountries_region ON individuals_countries(region)",
        "CREATE INDEX IF NOT EXISTS idx_indcountries_macro_region ON individuals_countries(macro_region)",
    ):
        conn.execute(ddl)
    conn.commit()
    log(f"[31] Inserted {inserted} rows.")
    return inserted


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.executescript(
                """
                CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, name_en TEXT,
                    nationalities_en TEXT, deathcity_en TEXT, birthcity_en TEXT);
                CREATE TABLE nationalities (name_en TEXT, iso_country_name TEXT, iso_a3_code TEXT);
                CREATE TABLE cities (name_en TEXT, iso_country_name TEXT, iso_a3_code TEXT);
                CREATE TABLE regions (macro_region TEXT, region TEXT, iso_a3 TEXT,
                    start_year INTEGER, end_year INTEGER);
                CREATE TABLE individuals_impact_date (wikidata_id TEXT, impact_date TEXT);
                """
            )
            insert_rows(seed, "individuals", [
                {"wikidata_id": "Q1", "name_en": "Alice", "nationalities_en": "French",
                 "deathcity_en": "Paris", "birthcity_en": "Lyon"},
                {"wikidata_id": "Q2", "name_en": "Bob", "nationalities_en": None,
                 "deathcity_en": "Boston", "birthcity_en": None},
                {"wikidata_id": "Q3", "name_en": "Carol", "nationalities_en": "Unknown",
                 "deathcity_en": None, "birthcity_en": "Atlantis"},
            ])
            insert_rows(seed, "nationalities", [
                {"name_en": "French", "iso_country_name": "France", "iso_a3_code": "FRA"},
            ])
            insert_rows(seed, "cities", [
                {"name_en": "Boston", "iso_country_name": "United States", "iso_a3_code": "USA"},
                {"name_en": "Lyon", "iso_country_name": "France", "iso_a3_code": "FRA"},
                {"name_en": "Paris", "iso_country_name": "France", "iso_a3_code": "FRA"},
            ])
            insert_rows(seed, "regions", [
                {"macro_region": "Europe", "region": "Western Europe", "iso_a3": "FRA",
                 "start_year": 1500, "end_year": 2100},
            ])
            insert_rows(seed, "individuals_impact_date", [
                {"wikidata_id": "Q1", "impact_date": "1850-01-01"},
            ])

        with open_db(db) as conn:
            n = run(conn)
            rows = conn.execute(
                "SELECT wikidata_id, iso_country_name, origins, region FROM individuals_countries"
            ).fetchall()
        log(f"[sample] inserted {n} rows")
        for r in rows:
            log(f"  individuals_countries: {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
