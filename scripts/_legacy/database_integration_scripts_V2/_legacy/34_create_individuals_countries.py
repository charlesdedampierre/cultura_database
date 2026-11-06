"""34 - Create individuals_countries (no region columns).

Mirrors `enhance_db/src/bin/34_create_individuals_countries.rs`.

Same priority chain (nationality > deathplace > birthplace) as 31/33 but
the output table here only has 5 columns (no region/macro_region).

  Inputs : individuals, nationalities, cities
  Output : individuals_countries (wikidata_id PK, name_en, iso_country_name,
                                   iso_a3_code, origins) + 3 indexes.

Usage
-----
    python3 34_create_individuals_countries.py            # synthetic DB
    python3 34_create_individuals_countries.py --full     # real DB
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from tqdm import tqdm

from common import DB_PATH, insert_rows, log, open_db, parse_run_mode

BATCH_SIZE = 50_000


def run(conn: sqlite3.Connection) -> int:
    log("[DB] 34: Creating individuals_countries (no regions)...")

    nat_lookup = {}
    for n, c, i in conn.execute(
        "SELECT name_en, iso_country_name, iso_a3_code FROM nationalities "
        "WHERE iso_country_name IS NOT NULL AND iso_a3_code IS NOT NULL"
    ):
        nat_lookup.setdefault(n, (c, i))

    city_lookup = {}
    for n, c, i in conn.execute(
        "SELECT name_en, iso_country_name, iso_a3_code FROM cities "
        "WHERE iso_country_name IS NOT NULL AND iso_a3_code IS NOT NULL"
    ):
        city_lookup.setdefault(n, (c, i))

    log(f"[34] nat={len(nat_lookup)} city={len(city_lookup)}")

    conn.execute("DROP TABLE IF EXISTS individuals_countries")
    conn.execute(
        """
        CREATE TABLE individuals_countries (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            iso_country_name TEXT,
            iso_a3_code TEXT,
            origins TEXT
        )
        """
    )

    total = conn.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]
    cursor = conn.execute(
        "SELECT wikidata_id, name_en, nationalities_en, deathcity_en, birthcity_en "
        "FROM individuals ORDER BY rowid"
    )
    sql = (
        "INSERT OR IGNORE INTO individuals_countries "
        "(wikidata_id, name_en, iso_country_name, iso_a3_code, origins) "
        "VALUES (?, ?, ?, ?, ?)"
    )
    inserted = 0
    buf: list[tuple] = []
    for wid, name_en, nats, dc, bc in tqdm(cursor, total=total, desc="34_indiv_countries"):
        found = None
        if nats:
            for n in nats.split("; "):
                hit = nat_lookup.get(n.strip())
                if hit:
                    found = (*hit, "nationality")
                    break
        if found is None and dc:
            hit = city_lookup.get(dc.strip())
            if hit:
                found = (*hit, "deathplace")
        if found is None and bc:
            hit = city_lookup.get(bc.strip())
            if hit:
                found = (*hit, "birthplace")
        if found is None:
            continue
        country, iso, origin = found
        buf.append((wid, name_en, country, iso, origin))
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
    ):
        conn.execute(ddl)
    conn.commit()
    log(f"[34] inserted {inserted}")
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
                """
            )
            insert_rows(seed, "individuals", [
                {"wikidata_id": "Q1", "name_en": "Alice", "nationalities_en": "French",
                 "deathcity_en": None, "birthcity_en": None},
                {"wikidata_id": "Q2", "name_en": "Bob", "nationalities_en": None,
                 "deathcity_en": "Boston", "birthcity_en": None},
            ])
            insert_rows(seed, "nationalities", [
                {"name_en": "French", "iso_country_name": "France", "iso_a3_code": "FRA"}])
            insert_rows(seed, "cities", [
                {"name_en": "Boston", "iso_country_name": "United States", "iso_a3_code": "USA"}])
        with open_db(db) as conn:
            n = run(conn)
            rows = conn.execute("SELECT * FROM individuals_countries").fetchall()
        log(f"[sample] {n}: {rows}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
