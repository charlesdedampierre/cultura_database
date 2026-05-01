"""51 — Rebuild individuals_countries (nationality -> birth -> death).

Mirrors `enhance_db/src/bin/51_rebuild_individuals_countries.rs`.

  Inputs : individuals (nationalities_en, birthcity_en, deathcity_en)
           nationalities (name_en, iso_country_name, iso_a3_code)
           cities        (name_en, iso_country_name, iso_a3_code)
  Output : individuals_countries (wikidata_id, name_en, iso_country_name,
                                    iso_a3_code, origins)

Usage
-----
    python3 51_rebuild_individuals_countries.py
    python3 51_rebuild_individuals_countries.py --full
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from tqdm import tqdm

from common import insert_rows, log, open_db, parse_run_mode


def _load_lookup(conn: sqlite3.Connection, sql: str) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for name, country, iso in conn.execute(sql):
        out.setdefault(name, (country, iso))
    return out


def run(conn: sqlite3.Connection) -> int:
    log("[DB] 51: Rebuild individuals_countries...")
    nat = _load_lookup(
        conn,
        "SELECT name_en, iso_country_name, iso_a3_code FROM nationalities "
        "WHERE iso_country_name IS NOT NULL AND iso_a3_code IS NOT NULL",
    )
    cities = _load_lookup(
        conn,
        "SELECT name_en, iso_country_name, iso_a3_code FROM cities "
        "WHERE iso_country_name IS NOT NULL AND iso_a3_code IS NOT NULL",
    )

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
    rows = conn.execute(
        "SELECT wikidata_id, name_en, nationalities_en, birthcity_en, deathcity_en "
        "FROM individuals"
    )
    inserted = 0
    cur = conn.cursor()
    cur.execute("BEGIN")
    for wid, name_en, nats, birth, death in tqdm(rows, total=total, desc="51", unit="row"):
        found = None
        if nats:
            for n in nats.split("; "):
                hit = nat.get(n.strip())
                if hit:
                    found = (*hit, "nationality")
                    break
        if not found and birth:
            hit = cities.get(birth.strip())
            if hit:
                found = (*hit, "birthplace")
        if not found and death:
            hit = cities.get(death.strip())
            if hit:
                found = (*hit, "deathplace")
        if not found:
            continue
        country, iso, origin = found
        cur.execute(
            "INSERT OR IGNORE INTO individuals_countries "
            "(wikidata_id, name_en, iso_country_name, iso_a3_code, origins) "
            "VALUES (?,?,?,?,?)",
            (wid, name_en, country, iso, origin),
        )
        inserted += 1
        if inserted % 50_000 == 0:
            conn.commit()
            cur.execute("BEGIN")
    conn.commit()
    log(f"[DB] inserted {inserted}")

    for sql in (
        "CREATE INDEX IF NOT EXISTS idx_indcountries_country ON individuals_countries(iso_country_name)",
        "CREATE INDEX IF NOT EXISTS idx_indcountries_iso ON individuals_countries(iso_a3_code)",
        "CREATE INDEX IF NOT EXISTS idx_indcountries_origins ON individuals_countries(origins)",
    ):
        conn.execute(sql)
    conn.commit()
    return inserted


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, "
                "name_en TEXT, nationalities_en TEXT, birthcity_en TEXT, "
                "deathcity_en TEXT)"
            )
            insert_rows(seed, "individuals", [
                {"wikidata_id": "Q1", "name_en": "Alice",
                 "nationalities_en": "French", "birthcity_en": "Paris",
                 "deathcity_en": None},
                {"wikidata_id": "Q2", "name_en": "Bob", "nationalities_en": None,
                 "birthcity_en": "Boston", "deathcity_en": None},
            ])
            seed.execute(
                "CREATE TABLE nationalities (name_en TEXT, "
                "iso_country_name TEXT, iso_a3_code TEXT)"
            )
            insert_rows(seed, "nationalities", [
                {"name_en": "French", "iso_country_name": "France", "iso_a3_code": "FRA"},
            ])
            seed.execute(
                "CREATE TABLE cities (name_en TEXT, "
                "iso_country_name TEXT, iso_a3_code TEXT)"
            )
            insert_rows(seed, "cities", [
                {"name_en": "Boston", "iso_country_name": "United States",
                 "iso_a3_code": "USA"},
                {"name_en": "Paris", "iso_country_name": "France", "iso_a3_code": "FRA"},
            ])
        with open_db(db) as conn:
            run(conn)
            for r in conn.execute("SELECT * FROM individuals_countries"):
                log(f"  {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
