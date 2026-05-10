"""23 — Rename columns + enrich cities with original-country wikidata id and
English Wikipedia URL.

Mirrors `enhance_db/src/bin/23_rename_columns_and_enrich_cities.rs`.

  Inputs : data/all_humans/place_locations.json
           data/all_humans/country_wikipedia_urls.json
           nationalities, cities, individuals_countries
  Output : nationalities.country_name -> iso_country_name
           cities.country_name -> original_country_name
           cities.modern_country_name -> iso_country_name
           cities.original_country_name_id, cities.en_wikipedia_url_country added
           individuals_countries.country_name -> iso_country_name
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from common import (
    ALL_HUMANS_DIR,
    DB_PATH,
    insert_rows,
    load_json,
    log,
    open_db,
    parse_run_mode,
    transaction,
)

PLACE_LOCATIONS_PATH = ALL_HUMANS_DIR / "place_locations.json"
COUNTRY_WIKI_PATH = ALL_HUMANS_DIR / "country_wikipedia_urls.json"


def run(
    conn: sqlite3.Connection,
    place_locations_path: Path = PLACE_LOCATIONS_PATH,
    country_wiki_path: Path = COUNTRY_WIKI_PATH,
) -> None:
    log("[DB] 23: Rename columns + enrich cities...")

    place_locations = load_json(place_locations_path)
    country_wiki = load_json(country_wiki_path)
    log(f"[23] Loaded {len(place_locations)} place_locations, {len(country_wiki)} country_wiki")

    city_country_id = {
        cid: v["country_id"]
        for cid, v in place_locations.items()
        if isinstance(v, dict) and v.get("country_id")
    }

    # 1. nationalities: rename country_name -> iso_country_name
    log("[23] Fixing nationalities...")
    conn.executescript(
        """
        CREATE TABLE nationalities_new (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            count INTEGER DEFAULT 0,
            description_en TEXT,
            instance_of TEXT,
            en_wikipedia_url TEXT,
            lat REAL,
            lon REAL,
            iso_country_name TEXT,
            iso_a3_code TEXT
        );
        INSERT INTO nationalities_new
        SELECT wikidata_id, name_en, count, description_en, instance_of,
               en_wikipedia_url, lat, lon, country_name, iso_a3_code FROM nationalities;
        DROP TABLE nationalities;
        ALTER TABLE nationalities_new RENAME TO nationalities;
        CREATE INDEX IF NOT EXISTS idx_nationalities_name ON nationalities(name_en);
        CREATE INDEX IF NOT EXISTS idx_nationalities_iso_country ON nationalities(iso_country_name);
        CREATE INDEX IF NOT EXISTS idx_nationalities_iso ON nationalities(iso_a3_code);
        """
    )

    # 2. cities: rename + add columns
    log("[23] Fixing cities...")
    cities = conn.execute(
        "SELECT id, name_en, lat, lon, country_name, modern_country_name, iso_a3_code FROM cities"
    ).fetchall()

    conn.execute("DROP TABLE IF EXISTS cities_new")
    conn.execute(
        """
        CREATE TABLE cities_new (
            id TEXT PRIMARY KEY,
            name_en TEXT,
            lat REAL,
            lon REAL,
            original_country_name TEXT,
            original_country_name_id TEXT,
            en_wikipedia_url_country TEXT,
            iso_country_name TEXT,
            iso_a3_code TEXT
        )
        """
    )

    rows_out = []
    for cid, name, lat, lon, country_name, modern_country_name, iso_a3_code in cities:
        country_id = city_country_id.get(cid)
        wiki_url = None
        if country_id:
            cw = country_wiki.get(country_id)
            if isinstance(cw, dict):
                wiki_url = cw.get("en_wikipedia_url")
        rows_out.append((
            cid, name, lat, lon, country_name, country_id, wiki_url,
            modern_country_name, iso_a3_code,
        ))

    with transaction(conn):
        conn.executemany(
            "INSERT INTO cities_new (id, name_en, lat, lon, original_country_name, "
            "original_country_name_id, en_wikipedia_url_country, iso_country_name, "
            "iso_a3_code) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows_out,
        )

    conn.executescript(
        """
        DROP TABLE cities;
        ALTER TABLE cities_new RENAME TO cities;
        CREATE INDEX IF NOT EXISTS idx_cities_name ON cities(name_en);
        CREATE INDEX IF NOT EXISTS idx_cities_iso_country ON cities(iso_country_name);
        CREATE INDEX IF NOT EXISTS idx_cities_iso ON cities(iso_a3_code);
        CREATE INDEX IF NOT EXISTS idx_cities_orig_country_id ON cities(original_country_name_id);
        """
    )

    # 3. individuals_countries: rename
    log("[23] Fixing individuals_countries...")
    conn.executescript(
        """
        CREATE TABLE individuals_countries_new (
            wikidata_id TEXT PRIMARY KEY,
            iso_country_name TEXT NOT NULL,
            iso_a3_code TEXT NOT NULL,
            origins TEXT NOT NULL
        );
        INSERT INTO individuals_countries_new
        SELECT wikidata_id, country_name, iso_a3_code, origins FROM individuals_countries;
        DROP TABLE individuals_countries;
        ALTER TABLE individuals_countries_new RENAME TO individuals_countries;
        CREATE INDEX IF NOT EXISTS idx_indcountries_iso_country ON individuals_countries(iso_country_name);
        CREATE INDEX IF NOT EXISTS idx_indcountries_iso ON individuals_countries(iso_a3_code);
        CREATE INDEX IF NOT EXISTS idx_indcountries_origins ON individuals_countries(origins);
        """
    )
    conn.commit()
    log("[23] Done.")


def _sample_main() -> None:
    place_locs = {
        "Q90": {"country_id": "Q142"},
        "Q60": {"country_id": "Q30"},
    }
    country_wiki = {
        "Q142": {"en_wikipedia_url": "https://en.wikipedia.org/wiki/France"},
        "Q30": {"en_wikipedia_url": "https://en.wikipedia.org/wiki/United_States"},
    }
    with tempfile.TemporaryDirectory() as tmp:
        pl = Path(tmp) / "place_locations.json"
        cw = Path(tmp) / "country_wikipedia_urls.json"
        pl.write_text(json.dumps(place_locs))
        cw.write_text(json.dumps(country_wiki))
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE nationalities (wikidata_id TEXT PRIMARY KEY, name_en TEXT, "
                "count INTEGER, description_en TEXT, instance_of TEXT, en_wikipedia_url TEXT, "
                "lat REAL, lon REAL, country_name TEXT, iso_a3_code TEXT)"
            )
            seed.execute(
                "CREATE TABLE cities (id TEXT PRIMARY KEY, name_en TEXT, lat REAL, lon REAL, "
                "country_name TEXT, modern_country_name TEXT, iso_a3_code TEXT)"
            )
            seed.execute(
                "CREATE TABLE individuals_countries (wikidata_id TEXT PRIMARY KEY, "
                "country_name TEXT, iso_a3_code TEXT, origins TEXT)"
            )
            insert_rows(seed, "nationalities", [
                {"wikidata_id": "Q142", "name_en": "French", "count": 1, "description_en": None,
                 "instance_of": None, "en_wikipedia_url": None, "lat": None, "lon": None,
                 "country_name": "France", "iso_a3_code": "FRA"},
            ])
            insert_rows(seed, "cities", [
                {"id": "Q90", "name_en": "Paris", "lat": 48.85, "lon": 2.35,
                 "country_name": "Kingdom of France", "modern_country_name": "France", "iso_a3_code": "FRA"},
                {"id": "Q60", "name_en": "New York", "lat": 40.7, "lon": -74.0,
                 "country_name": "United States", "modern_country_name": "United States", "iso_a3_code": "USA"},
            ])
            insert_rows(seed, "individuals_countries", [
                {"wikidata_id": "P1", "country_name": "France", "iso_a3_code": "FRA", "origins": "nationality"},
            ])
        with open_db(db) as conn:
            run(conn, place_locations_path=pl, country_wiki_path=cw)
            for row in conn.execute("SELECT * FROM cities"):
                log(f"  cities: {row}")
            for row in conn.execute("SELECT * FROM individuals_countries"):
                log(f"  ind_countries: {row}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db(DB_PATH) as conn:
            run(conn)
    else:
        _sample_main()
