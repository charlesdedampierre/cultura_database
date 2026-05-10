"""55 — Rebuild individuals_countries with impact_year column.

Mirrors `enhance_db/src/bin/55_rebuild_individuals_countries.rs`.

Same priority order as step 51 (nationality -> birth -> death) but
also stores the impact_year (from individuals_impact_date) on each row.

Usage
-----
    python3 55_rebuild_individuals_countries.py
    python3 55_rebuild_individuals_countries.py --full
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from tqdm import tqdm

from common import insert_rows, log, open_db, parse_run_mode, parse_year


def _load_lookup(conn: sqlite3.Connection, sql: str) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for name, country, iso in conn.execute(sql):
        out.setdefault(name, (country, iso))
    return out


def run(conn: sqlite3.Connection) -> int:
    log("[DB] 55: Rebuild individuals_countries (with impact_year)...")
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
    impact: dict[str, int] = {}
    for wid, ds in conn.execute(
        "SELECT wikidata_id, impact_date FROM individuals_impact_date"
    ):
        y = parse_year(ds)
        if y is not None:
            impact[wid] = y

    conn.execute("DROP TABLE IF EXISTS individuals_countries")
    conn.execute(
        """
        CREATE TABLE individuals_countries (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            iso_country_name TEXT,
            iso_a3_code TEXT,
            origins TEXT,
            impact_year INTEGER
        )
        """
    )

    total = conn.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]
    inserted = 0
    cur = conn.cursor()
    cur.execute("BEGIN")
    for wid, name_en, nats, birth, death in tqdm(
        conn.execute(
            "SELECT wikidata_id, name_en, nationalities_en, birthcity_en, "
            "deathcity_en FROM individuals"
        ),
        total=total, desc="55", unit="row",
    ):
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
            "(wikidata_id, name_en, iso_country_name, iso_a3_code, origins, impact_year) "
            "VALUES (?,?,?,?,?,?)",
            (wid, name_en, country, iso, origin, impact.get(wid)),
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
        "CREATE INDEX IF NOT EXISTS idx_indcountries_impact_year ON individuals_countries(impact_year)",
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
                {"name_en": "Paris", "iso_country_name": "France", "iso_a3_code": "FRA"},
            ])
            seed.execute(
                "CREATE TABLE individuals_impact_date "
                "(wikidata_id TEXT, impact_date TEXT)"
            )
            insert_rows(seed, "individuals_impact_date", [
                {"wikidata_id": "Q1", "impact_date": "1850"},
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
