"""29 — Add `region` and `macro_region` columns to `individuals_countries`,
populated by joining each individual's impact_date to the regions table's
date ranges. Multiple matching values are joined with '; '.

Mirrors `enhance_db/src/bin/29_add_regions_to_individuals_countries.rs`.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import (
    DB_PATH,
    add_column_if_missing,
    column_exists,
    insert_rows,
    log,
    open_db,
    parse_run_mode,
    parse_year,
    transaction,
)

BATCH_SIZE = 50_000


def run(conn: sqlite3.Connection) -> None:
    log("[DB] 29: Add regions to individuals_countries...")

    region_lookup: dict[str, list[tuple[str, str, int, int | None]]] = {}
    for macro_r, region, iso, start, end in conn.execute(
        "SELECT macro_region, region, iso_a3, start_year, end_year FROM regions"
    ):
        region_lookup.setdefault(iso, []).append((macro_r, region, start, end))
    log(f"[29] Region lookup: {len(region_lookup)} country codes")

    impact_lookup: dict[str, int] = {}
    for wid, date_str in conn.execute(
        "SELECT wikidata_id, impact_date FROM individuals_impact_date"
    ):
        y = parse_year(date_str)
        if y is not None:
            impact_lookup[wid] = y
    log(f"[29] Impact date lookup: {len(impact_lookup)} entries")

    if not column_exists(conn, "individuals_countries", "region"):
        add_column_if_missing(conn, "individuals_countries", "region", "TEXT")
        add_column_if_missing(conn, "individuals_countries", "macro_region", "TEXT")
    else:
        conn.execute("UPDATE individuals_countries SET region = NULL, macro_region = NULL")
        conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM individuals_countries").fetchone()[0]
    log(f"[29] Total individuals_countries: {total}")

    cur = conn.execute("SELECT wikidata_id, iso_a3_code FROM individuals_countries")
    try:
        from tqdm import tqdm
        iterator = tqdm(cur, total=total, desc="29_regions", unit="row")
    except ImportError:
        iterator = cur

    matched = unmatched = no_impact = 0
    update_sql = "UPDATE individuals_countries SET region = ?, macro_region = ? WHERE wikidata_id = ?"
    buf: list[tuple] = []
    with transaction(conn):
        ins = conn.cursor()
        for wid, iso in iterator:
            year = impact_lookup.get(wid)
            if year is None:
                no_impact += 1
                continue
            entries = region_lookup.get(iso)
            if not entries:
                unmatched += 1
                continue
            regions: list[str] = []
            macros: list[str] = []
            for macro_r, region, start, end in entries:
                in_range = year >= start and (end is None or year <= end)
                if in_range:
                    if region not in regions:
                        regions.append(region)
                    if macro_r not in macros:
                        macros.append(macro_r)
            if regions:
                buf.append(("; ".join(regions), "; ".join(macros), wid))
                matched += 1
                if len(buf) >= BATCH_SIZE:
                    ins.executemany(update_sql, buf)
                    buf.clear()
            else:
                unmatched += 1
        if buf:
            ins.executemany(update_sql, buf)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_indcountries_region ON individuals_countries(region)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_indcountries_macro_region ON individuals_countries(macro_region)")
    conn.commit()
    log(f"[29] Matched {matched}, unmatched {unmatched}, no impact date {no_impact}")


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE regions (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "macro_region TEXT, region TEXT, iso_country_name TEXT, iso_a3 TEXT, "
                "start_year INTEGER, end_year INTEGER)"
            )
            seed.execute(
                "CREATE TABLE individuals_impact_date (wikidata_id TEXT PRIMARY KEY, impact_date TEXT)"
            )
            seed.execute(
                "CREATE TABLE individuals_countries (wikidata_id TEXT PRIMARY KEY, "
                "name_en TEXT, iso_country_name TEXT, iso_a3_code TEXT, origins TEXT)"
            )
            insert_rows(seed, "regions", [
                {"macro_region": "Western Europe", "region": "France",
                 "iso_country_name": "France", "iso_a3": "FRA", "start_year": 500, "end_year": None},
                {"macro_region": "Ancient Mediterranean", "region": "Latin World",
                 "iso_country_name": "France", "iso_a3": "FRA", "start_year": -300, "end_year": 500},
                {"macro_region": "Western Europe", "region": "Italy",
                 "iso_country_name": "Italy", "iso_a3": "ITA", "start_year": 500, "end_year": None},
            ])
            insert_rows(seed, "individuals_impact_date", [
                {"wikidata_id": "P1", "impact_date": "1850-01-01"},
                {"wikidata_id": "P2", "impact_date": "0100-01-01"},
                {"wikidata_id": "P3", "impact_date": "1900-06-01"},
            ])
            insert_rows(seed, "individuals_countries", [
                {"wikidata_id": "P1", "name_en": "Hugo", "iso_country_name": "France",
                 "iso_a3_code": "FRA", "origins": "nationality"},
                {"wikidata_id": "P2", "name_en": "Cicero", "iso_country_name": "France",
                 "iso_a3_code": "FRA", "origins": "birthplace"},
                {"wikidata_id": "P3", "name_en": "Verdi", "iso_country_name": "Italy",
                 "iso_a3_code": "ITA", "origins": "nationality"},
            ])

        with open_db(db) as conn:
            run(conn)
            for row in conn.execute(
                "SELECT wikidata_id, iso_a3_code, region, macro_region "
                "FROM individuals_countries ORDER BY wikidata_id"
            ):
                log(f"  {row}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db(DB_PATH) as conn:
            run(conn)
    else:
        _sample_main()
