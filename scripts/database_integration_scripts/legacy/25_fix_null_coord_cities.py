"""25 — Recover `iso_country` for null-coord cities by joining
`original_country_name` to `modern_country.name`, then rebuild
`individuals_countries`.

Mirrors `enhance_db/src/bin/25_fix_null_coord_cities.rs`.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import (
    DB_PATH,
    insert_rows,
    log,
    open_db,
    parse_run_mode,
    transaction,
)

BATCH_SIZE = 50_000


def _rebuild(conn: sqlite3.Connection) -> None:
    nat_lookup: dict[str, tuple[str, str]] = {}
    for n, c, i in conn.execute(
        "SELECT name_en, iso_country_name, iso_a3_code FROM nationalities "
        "WHERE iso_country_name IS NOT NULL AND iso_a3_code IS NOT NULL"
    ):
        nat_lookup[n] = (c, i)
    city_lookup: dict[str, tuple[str, str]] = {}
    for n, c, i in conn.execute(
        "SELECT name_en, iso_country_name, iso_a3_code FROM cities "
        "WHERE iso_country_name IS NOT NULL AND iso_a3_code IS NOT NULL"
    ):
        if n not in city_lookup:
            city_lookup[n] = (c, i)
    log(f"[25] Lookups: nat={len(nat_lookup)} city={len(city_lookup)}")

    conn.execute("DROP TABLE IF EXISTS individuals_countries")
    conn.execute(
        """
        CREATE TABLE individuals_countries (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            iso_country_name TEXT NOT NULL,
            iso_a3_code TEXT NOT NULL,
            origins TEXT NOT NULL
        )
        """
    )

    total = conn.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]
    cur = conn.execute(
        "SELECT wikidata_id, name_en, nationalities_en, deathcity_en, birthcity_en FROM individuals"
    )
    try:
        from tqdm import tqdm
        iterator = tqdm(cur, total=total, desc="25_rebuild", unit="row")
    except ImportError:
        iterator = cur

    matched_nat = matched_death = matched_birth = unmatched = 0
    insert_sql = (
        "INSERT OR IGNORE INTO individuals_countries "
        "(wikidata_id, name_en, iso_country_name, iso_a3_code, origins) "
        "VALUES (?, ?, ?, ?, ?)"
    )
    buf: list[tuple] = []
    with transaction(conn):
        ins = conn.cursor()
        for wid, name, nats, death, birth in iterator:
            row = None
            if nats:
                for nm in nats.split("; "):
                    hit = nat_lookup.get(nm.strip())
                    if hit:
                        row = (wid, name, hit[0], hit[1], "nationality")
                        matched_nat += 1
                        break
            if row is None and death:
                hit = city_lookup.get(death.strip())
                if hit:
                    row = (wid, name, hit[0], hit[1], "deathplace")
                    matched_death += 1
            if row is None and birth:
                hit = city_lookup.get(birth.strip())
                if hit:
                    row = (wid, name, hit[0], hit[1], "birthplace")
                    matched_birth += 1
            if row is None:
                unmatched += 1
            else:
                buf.append(row)
                if len(buf) >= BATCH_SIZE:
                    ins.executemany(insert_sql, buf)
                    buf.clear()
        if buf:
            ins.executemany(insert_sql, buf)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_indcountries_iso_country ON individuals_countries(iso_country_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_indcountries_iso ON individuals_countries(iso_a3_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_indcountries_origins ON individuals_countries(origins)")
    conn.commit()
    final = conn.execute("SELECT COUNT(*) FROM individuals_countries").fetchone()[0]
    log(f"[25] Final: {final} (nat:{matched_nat} death:{matched_death} birth:{matched_birth} unmatched:{unmatched})")


def run(conn: sqlite3.Connection) -> None:
    log("[DB] 25: Recover iso_country for null-coord cities + rebuild...")

    null_before = conn.execute(
        "SELECT COUNT(*) FROM cities WHERE iso_country_name IS NULL"
    ).fetchone()[0]
    log(f"[25] Cities NULL iso_country: {null_before}")

    updated = conn.execute(
        """
        UPDATE cities
        SET iso_country_name = (SELECT mc.name FROM modern_country mc
                                 WHERE mc.name = cities.original_country_name LIMIT 1),
            iso_a3_code = (SELECT mc.iso_a3_code FROM modern_country mc
                           WHERE mc.name = cities.original_country_name LIMIT 1)
        WHERE iso_country_name IS NULL
          AND original_country_name IS NOT NULL
          AND EXISTS (SELECT 1 FROM modern_country mc WHERE mc.name = cities.original_country_name)
        """
    ).rowcount
    conn.commit()
    log(f"[25] Recovered iso_country for {updated} cities")

    _rebuild(conn)


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE modern_country (id TEXT PRIMARY KEY, name TEXT, iso_a3_code TEXT)"
            )
            seed.execute(
                """
                CREATE TABLE cities (
                    id TEXT PRIMARY KEY, name_en TEXT, lat REAL, lon REAL,
                    original_country_name TEXT, iso_country_name TEXT, iso_a3_code TEXT
                )
                """
            )
            seed.execute(
                "CREATE TABLE nationalities (name_en TEXT, iso_country_name TEXT, iso_a3_code TEXT)"
            )
            seed.execute(
                "CREATE TABLE individuals (wikidata_id TEXT, name_en TEXT, "
                "nationalities_en TEXT, deathcity_en TEXT, birthcity_en TEXT)"
            )
            insert_rows(seed, "modern_country", [
                {"id": "Q142", "name": "France", "iso_a3_code": "FRA"},
                {"id": "Q29", "name": "Spain", "iso_a3_code": "ESP"},
            ])
            insert_rows(seed, "cities", [
                {"id": "QA", "name_en": "Madrid", "lat": None, "lon": None,
                 "original_country_name": "Spain", "iso_country_name": None, "iso_a3_code": None},
                {"id": "QB", "name_en": "Paris", "lat": 48.85, "lon": 2.35,
                 "original_country_name": "Kingdom of France", "iso_country_name": "France", "iso_a3_code": "FRA"},
            ])
            insert_rows(seed, "nationalities", [
                {"name_en": "French", "iso_country_name": "France", "iso_a3_code": "FRA"},
            ])
            insert_rows(seed, "individuals", [
                {"wikidata_id": "P1", "name_en": "X", "nationalities_en": None,
                 "deathcity_en": "Madrid", "birthcity_en": None},
            ])
        with open_db(db) as conn:
            run(conn)
            for row in conn.execute("SELECT id, iso_country_name, iso_a3_code FROM cities"):
                log(f"  cities: {row}")
            for row in conn.execute("SELECT * FROM individuals_countries"):
                log(f"  ind_countries: {row}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db(DB_PATH) as conn:
            run(conn)
    else:
        _sample_main()
