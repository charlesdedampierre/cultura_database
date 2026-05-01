"""07 - Clean the properties_definition table.

Mirrors `enhance_db/src/bin/07_clean_properties_definition.rs`.

  Inputs : properties_definition (must exist with `used_for` column)
  Output : same table with all `used_for = 'identifier'` rows removed,
           plus new `table_name` and `column_name` columns populated
           with a static mapping for known properties and `used_for`
           as a fallback for the rest.

Usage
-----
    python3 07_clean_properties_definition.py
    python3 07_clean_properties_definition.py --full
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import (
    add_column_if_missing,
    insert_rows,
    log,
    open_db,
    parse_run_mode,
)

PROPERTY_MAP: list[tuple[str, str, str]] = [
    ("P21", "individuals", "gender"),
    ("P27", "nationalities", "name_en"),
    ("P106", "occupations", "name_en"),
    ("P569", "individuals", "birthdate"),
    ("P570", "individuals", "deathdate"),
    ("P19", "cities", "name_en (birthcity)"),
    ("P20", "cities", "name_en (deathcity)"),
    ("P6886", "writing_languages", "name"),
    ("P31", "occupations / nationalities", "instance_of"),
    ("P17", "cities / nationalities", "modern_country_name"),
    ("P625", "cities / nationalities", "lat, lon"),
    ("P36", "nationalities", "lat, lon (via capital)"),
    ("P30", "modern_country", "continent"),
    ("P298", "modern_country", "iso_a3_code"),
    ("P1566", "cities", "id (GeoNames)"),
]


def run(conn: sqlite3.Connection) -> None:
    log("[DB] 07: Cleaning properties_definition table...")

    id_count = conn.execute(
        "SELECT COUNT(*) FROM properties_definition WHERE used_for = 'identifier'"
    ).fetchone()[0]
    log(f"[DB] Removing {id_count} identifier properties from properties_definition")
    conn.execute("DELETE FROM properties_definition WHERE used_for = 'identifier'")
    conn.commit()

    remaining = conn.execute(
        "SELECT COUNT(*) FROM properties_definition"
    ).fetchone()[0]
    log(f"[DB] {remaining} properties remaining after removal")

    if add_column_if_missing(conn, "properties_definition", "table_name", "TEXT"):
        log("[DB] Added table_name column")
    if add_column_if_missing(conn, "properties_definition", "column_name", "TEXT"):
        log("[DB] Added column_name column")

    conn.executemany(
        "UPDATE properties_definition SET table_name = ?, column_name = ? "
        "WHERE property_id = ?",
        [(t, c, p) for p, t, c in PROPERTY_MAP],
    )
    conn.execute(
        "UPDATE properties_definition SET table_name = 'individuals', "
        "column_name = used_for "
        "WHERE table_name IS NULL AND used_for IS NOT NULL"
    )
    conn.commit()
    log("[DB] 07: Done. Cleaned properties_definition.")


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db_path) as seed:
            seed.execute(
                "CREATE TABLE properties_definition ("
                "property_id TEXT PRIMARY KEY, property_name TEXT, "
                "description TEXT, wikidata_url TEXT, used_for TEXT)"
            )
            insert_rows(seed, "properties_definition", [
                {"property_id": "P21", "property_name": "sex or gender",
                 "description": None, "wikidata_url": None, "used_for": "gender"},
                {"property_id": "P213", "property_name": "ISNI",
                 "description": None, "wikidata_url": None, "used_for": "identifier"},
                {"property_id": "P9999", "property_name": "weird",
                 "description": None, "wikidata_url": None, "used_for": "weirdness"},
            ])
            seed.commit()

        with open_db(db_path) as conn:
            run(conn)
            rows = conn.execute(
                "SELECT property_id, property_name, table_name, column_name "
                "FROM properties_definition ORDER BY property_id"
            ).fetchall()
        for r in rows:
            log(f"  properties_definition: {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
