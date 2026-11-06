"""44 - Reset properties_definition with the canonical Wikidata properties used.

Mirrors `enhance_db/src/bin/44_fix_properties_definition.rs`.

  Inputs : (none — list is hard-coded)
  Output : properties_definition (property_id PK, property_name, description,
           table_name, column_name) populated with 18 entries.

Usage
-----
    python3 44_fix_properties_definition.py            # synthetic
    python3 44_fix_properties_definition.py --full     # real DB
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import log, open_db, parse_run_mode

PROPERTIES: list[tuple[str, str, str, str, str]] = [
    ("P17", "country",
     "sovereign state that this item is in; used to map cities and nationalities to modern countries",
     "cities, nationalities", "iso_country_name, iso_a3_code"),
    ("P19", "place of birth", "most specific known birth location of a person",
     "individuals, cities", "birthcity_en"),
    ("P20", "place of death", "most specific known death location of a person",
     "individuals, cities", "deathcity_en"),
    ("P21", "sex or gender", "sex or gender identity of human or animal",
     "individuals", "gender"),
    ("P27", "country of citizenship",
     "the object is a country that recognizes the subject as its citizen",
     "individuals, nationalities",
     "nationalities_en (individuals), name_en (nationalities)"),
    ("P30", "continent", "continent of which the subject is a part",
     "modern_country", "continent"),
    ("P31", "instance of", "type to which this subject corresponds/belongs",
     "nationalities", "instance_of"),
    ("P36", "capital",
     "seat of government of a country, province, state or other type of administrative territorial entity; "
     "used to resolve nationality-to-country mappings via capital city",
     "nationalities", "iso_modern_country_origin (capital_city method)"),
    ("P106", "occupation",
     "occupation of a person; used to select individuals (scientists, writers, artists) "
     "and populate the occupations table",
     "individuals, occupations",
     "occupations_en (individuals), name_en (occupations)"),
    ("P131", "located in the administrative territorial entity",
     "the item is located on the territory of the following administrative entity; "
     "used in nationality-to-country resolution chain",
     "nationalities", "iso_modern_country_origin (qlever_relation method)"),
    ("P279", "subclass of",
     "this item is a subclass of that item; used to build the occupation hierarchy (meta_occupation)",
     "occupations", "meta_occupation"),
    ("P297", "ISO 3166-1 alpha-2 code",
     "two-letter country code per ISO 3166-1; used during extraction to identify countries",
     "modern_country", "(used in extraction, not stored as column)"),
    ("P298", "ISO 3166-1 alpha-3 code", "three-letter country code per ISO 3166-1",
     "modern_country, nationalities, cities, individuals_countries, individuals_regions, regions",
     "iso_a3_code (or iso_a3)"),
    ("P569", "date of birth", "date on which the subject was born",
     "individuals", "birthdate, birthdate_precision"),
    ("P570", "date of death", "date on which the subject died",
     "individuals", "deathdate, deathdate_precision"),
    ("P625", "coordinate location",
     "geocoordinates of the subject (WGS84); used for cities and nationalities",
     "cities, nationalities", "lat, lon"),
    ("P856", "official website",
     "URL of the official page of an item; stored in identifier_types for external identifier systems",
     "identifier_types", "website"),
    ("P1366", "replaced by",
     "other entity that the subject was replaced by; "
     "used to trace historical nationalities to their modern successor countries",
     "nationalities", "iso_modern_country_origin (qlever_replaced_by method)"),
    ("P6886", "writing language", "language in which the writer has written their work",
     "writing_languages, individual_writing_languages, individuals",
     "name (writing_languages), language_name (individual_writing_languages), "
     "writing_language_name_en (individuals)"),
]


def run(conn: sqlite3.Connection) -> int:
    log("[DB] 44: Fixing properties_definition...")
    conn.execute("DROP TABLE IF EXISTS properties_definition")
    conn.execute(
        """
        CREATE TABLE properties_definition (
            property_id TEXT PRIMARY KEY,
            property_name TEXT,
            description TEXT,
            table_name TEXT,
            column_name TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO properties_definition "
        "(property_id, property_name, description, table_name, column_name) "
        "VALUES (?, ?, ?, ?, ?)",
        PROPERTIES,
    )
    conn.commit()
    log(f"[44] inserted {len(PROPERTIES)} rows")
    return len(PROPERTIES)


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            # Pre-existing junk row to confirm the table is dropped/recreated.
            seed.execute(
                "CREATE TABLE properties_definition (property_id TEXT, property_name TEXT, "
                "description TEXT, table_name TEXT, column_name TEXT)"
            )
            seed.execute("INSERT INTO properties_definition VALUES ('Pjunk', 'old', '', '', '')")
        with open_db(db) as conn:
            n = run(conn)
            sample = conn.execute(
                "SELECT property_id, property_name FROM properties_definition "
                "ORDER BY property_id LIMIT 5"
            ).fetchall()
        log(f"[sample] {n} props; first 5: {sample}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
