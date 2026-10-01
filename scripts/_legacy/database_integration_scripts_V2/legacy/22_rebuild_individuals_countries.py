"""22 — Rebuild `individuals_countries` using updated `cities.modern_country_name`.

Mirrors `enhance_db/src/bin/22_rebuild_individuals_countries.rs`.

Same priority logic as 20 but the city lookup now uses
`modern_country_name` + `iso_a3_code` (from script 21).
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


def run(conn: sqlite3.Connection) -> None:
    log("[DB] 22: Rebuild individuals_countries with modern city data...")

    nat_lookup: dict[str, tuple[str, str]] = {}
    for n, c, i in conn.execute(
        "SELECT name_en, country_name, iso_a3_code FROM nationalities "
        "WHERE country_name IS NOT NULL AND iso_a3_code IS NOT NULL"
    ):
        nat_lookup[n] = (c, i)

    city_lookup: dict[str, tuple[str, str]] = {}
    for n, c, i in conn.execute(
        "SELECT name_en, modern_country_name, iso_a3_code FROM cities "
        "WHERE modern_country_name IS NOT NULL AND iso_a3_code IS NOT NULL"
    ):
        if n not in city_lookup:
            city_lookup[n] = (c, i)
    log(f"[22] Lookups: nat={len(nat_lookup)} city={len(city_lookup)}")

    conn.execute("DROP TABLE IF EXISTS individuals_countries")
    conn.execute(
        """
        CREATE TABLE individuals_countries (
            wikidata_id TEXT PRIMARY KEY,
            country_name TEXT NOT NULL,
            iso_a3_code TEXT NOT NULL,
            origins TEXT NOT NULL
        )
        """
    )

    total = conn.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]
    cur = conn.execute(
        "SELECT wikidata_id, nationalities_en, deathcity_en, birthcity_en FROM individuals"
    )
    try:
        from tqdm import tqdm
        iterator = tqdm(cur, total=total, desc="22_rebuild", unit="row")
    except ImportError:
        iterator = cur

    matched_nat = matched_death = matched_birth = unmatched = 0
    insert_sql = (
        "INSERT OR IGNORE INTO individuals_countries "
        "(wikidata_id, country_name, iso_a3_code, origins) VALUES (?, ?, ?, ?)"
    )
    buf: list[tuple] = []

    with transaction(conn):
        ins = conn.cursor()
        for wid, nats, death, birth in iterator:
            row = None
            if nats:
                for nm in nats.split("; "):
                    hit = nat_lookup.get(nm.strip())
                    if hit:
                        row = (wid, hit[0], hit[1], "nationality")
                        matched_nat += 1
                        break
            if row is None and death:
                hit = city_lookup.get(death.strip())
                if hit:
                    row = (wid, hit[0], hit[1], "deathplace")
                    matched_death += 1
            if row is None and birth:
                hit = city_lookup.get(birth.strip())
                if hit:
                    row = (wid, hit[0], hit[1], "birthplace")
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

    conn.execute("CREATE INDEX IF NOT EXISTS idx_indcountries_country ON individuals_countries(country_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_indcountries_iso ON individuals_countries(iso_a3_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_indcountries_origins ON individuals_countries(origins)")
    conn.commit()
    final = conn.execute("SELECT COUNT(*) FROM individuals_countries").fetchone()[0]
    log(f"[22] Inserted {final} (nat:{matched_nat} death:{matched_death} birth:{matched_birth} unmatched:{unmatched})")


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, "
                "nationalities_en TEXT, deathcity_en TEXT, birthcity_en TEXT)"
            )
            seed.execute(
                "CREATE TABLE nationalities (name_en TEXT, country_name TEXT, iso_a3_code TEXT)"
            )
            seed.execute(
                "CREATE TABLE cities (name_en TEXT, modern_country_name TEXT, iso_a3_code TEXT)"
            )
            insert_rows(seed, "nationalities", [
                {"name_en": "French", "country_name": "France", "iso_a3_code": "FRA"},
            ])
            insert_rows(seed, "cities", [
                {"name_en": "Paris", "modern_country_name": "France", "iso_a3_code": "FRA"},
                {"name_en": "Constantinople", "modern_country_name": "Turkey", "iso_a3_code": "TUR"},
            ])
            insert_rows(seed, "individuals", [
                {"wikidata_id": "P1", "nationalities_en": "French", "deathcity_en": None, "birthcity_en": None},
                {"wikidata_id": "P2", "nationalities_en": None, "deathcity_en": "Constantinople", "birthcity_en": None},
                {"wikidata_id": "P3", "nationalities_en": None, "deathcity_en": None, "birthcity_en": "Paris"},
            ])
        with open_db(db) as conn:
            run(conn)
            for row in conn.execute(
                "SELECT * FROM individuals_countries ORDER BY wikidata_id"
            ):
                log(f"  {row}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db(DB_PATH) as conn:
            run(conn)
    else:
        _sample_main()
