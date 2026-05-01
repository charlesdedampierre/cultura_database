"""20 — Create `individuals_countries` from a 3-priority match
(nationality -> deathplace -> birthplace).

Mirrors `enhance_db/src/bin/20_create_individuals_countries.rs`.

  Inputs : individuals (wikidata_id, nationalities_en, deathcity_en, birthcity_en)
           nationalities (name_en, country_name, iso_a3_code)
           cities (name_en, country_name, iso_a3)
  Output : individuals_countries (wikidata_id PK, country_name, iso_a3_code, origins)
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
    log("[DB] 20: Create individuals_countries...")

    nat_lookup: dict[str, tuple[str, str]] = {}
    for name, country, iso in conn.execute(
        "SELECT name_en, country_name, iso_a3_code FROM nationalities "
        "WHERE country_name IS NOT NULL AND iso_a3_code IS NOT NULL"
    ):
        nat_lookup[name] = (country, iso)
    log(f"[20] Nationality lookup: {len(nat_lookup)} entries")

    city_lookup: dict[str, tuple[str, str]] = {}
    for name, country, iso in conn.execute(
        "SELECT name_en, country_name, iso_a3 FROM cities "
        "WHERE country_name IS NOT NULL AND iso_a3 IS NOT NULL"
    ):
        if name not in city_lookup:
            city_lookup[name] = (country, iso)
    log(f"[20] City lookup: {len(city_lookup)} entries")

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
    log(f"[20] Total individuals: {total}")

    cur = conn.execute(
        "SELECT wikidata_id, nationalities_en, deathcity_en, birthcity_en FROM individuals"
    )
    try:
        from tqdm import tqdm
        iterator = tqdm(cur, total=total, desc="ind_countries", unit="row")
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
                for n in nats.split("; "):
                    hit = nat_lookup.get(n.strip())
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
    log(f"[20] Inserted {final} (nat:{matched_nat} death:{matched_death} birth:{matched_birth} unmatched:{unmatched})")


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, name_en TEXT, "
                "nationalities_en TEXT, deathcity_en TEXT, birthcity_en TEXT)"
            )
            seed.execute(
                "CREATE TABLE nationalities (wikidata_id TEXT, name_en TEXT, "
                "country_name TEXT, iso_a3_code TEXT)"
            )
            seed.execute(
                "CREATE TABLE cities (id TEXT, name_en TEXT, country_name TEXT, iso_a3 TEXT)"
            )
            insert_rows(seed, "nationalities", [
                {"wikidata_id": "Q142", "name_en": "French", "country_name": "France", "iso_a3_code": "FRA"},
                {"wikidata_id": "Q30", "name_en": "American", "country_name": "United States", "iso_a3_code": "USA"},
            ])
            insert_rows(seed, "cities", [
                {"id": "Q90", "name_en": "Paris", "country_name": "France", "iso_a3": "FRA"},
                {"id": "Q60", "name_en": "New York", "country_name": "United States", "iso_a3": "USA"},
            ])
            insert_rows(seed, "individuals", [
                {"wikidata_id": "P1", "name_en": "Hugo", "nationalities_en": "French",
                 "deathcity_en": None, "birthcity_en": None},
                {"wikidata_id": "P2", "name_en": "Smith", "nationalities_en": None,
                 "deathcity_en": "New York", "birthcity_en": None},
                {"wikidata_id": "P3", "name_en": "Doe", "nationalities_en": None,
                 "deathcity_en": None, "birthcity_en": "Paris"},
                {"wikidata_id": "P4", "name_en": "Nobody", "nationalities_en": None,
                 "deathcity_en": None, "birthcity_en": None},
            ])

        with open_db(db) as conn:
            run(conn)
            for row in conn.execute(
                "SELECT wikidata_id, country_name, iso_a3_code, origins FROM individuals_countries ORDER BY wikidata_id"
            ):
                log(f"  {row}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db(DB_PATH) as conn:
            run(conn)
    else:
        _sample_main()
