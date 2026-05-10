"""33 - Create individuals_countries (with region/macro_region).

Mirrors `enhance_db/src/bin/33_create_individuals_countries.rs`.

Same logic as 31, but on the post-transfer clean DB. Inputs/outputs are
identical to 31; the only difference in Rust is which DB path is opened.

Usage
-----
    python3 33_create_individuals_countries.py            # synthetic DB
    python3 33_create_individuals_countries.py --full     # real DB
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import importlib.util

from common import DB_PATH, insert_rows, log, open_db, parse_run_mode

# Reuse the run() implementation from 31 — it is byte-for-byte the same.
_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "_rebuild_31", _HERE / "31_rebuild_individuals_countries.py"
)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)


def run(conn: sqlite3.Connection) -> int:
    return _mod.run(conn)


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
            ])
            insert_rows(seed, "nationalities", [
                {"name_en": "French", "iso_country_name": "France", "iso_a3_code": "FRA"}])
            insert_rows(seed, "cities", [
                {"name_en": "Paris", "iso_country_name": "France", "iso_a3_code": "FRA"}])
            insert_rows(seed, "regions", [
                {"macro_region": "Europe", "region": "Western Europe", "iso_a3": "FRA",
                 "start_year": 1500, "end_year": 2100}])
            insert_rows(seed, "individuals_impact_date", [
                {"wikidata_id": "Q1", "impact_date": "1850"}])

        with open_db(db) as conn:
            n = run(conn)
            rows = conn.execute("SELECT * FROM individuals_countries").fetchall()
        log(f"[sample] {n} rows: {rows}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db(DB_PATH.parent / "humans_clean_new.sqlite3") as conn:
            run(conn)
    else:
        _sample_main()
