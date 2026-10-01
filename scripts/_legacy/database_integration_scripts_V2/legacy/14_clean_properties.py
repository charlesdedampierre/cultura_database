"""14 - Drop the `used_for` column from properties_definition.

Mirrors `enhance_db/src/bin/14_clean_properties.rs`.

  Inputs : properties_definition (with `used_for` column)
  Output : properties_definition rebuilt without `used_for`. Other
           columns kept: property_id (PK), property_name, description,
           wikidata_url, table_name, column_name.

Usage
-----
    python3 14_clean_properties.py
    python3 14_clean_properties.py --full
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import (
    column_exists,
    insert_rows,
    log,
    open_db,
    parse_run_mode,
)


def run(conn: sqlite3.Connection) -> None:
    log("=== Step 14: Remove used_for column from properties_definition ===")

    cols_before = [r[1] for r in conn.execute("PRAGMA table_info(properties_definition)").fetchall()]
    log(f"[14] Current columns: {', '.join(cols_before)}")

    if not column_exists(conn, "properties_definition", "used_for"):
        log("[14] Column used_for does not exist, nothing to do.")
        return

    log("[14] Removing used_for column...")
    conn.executescript(
        """
        DROP TABLE IF EXISTS properties_definition_backup;
        ALTER TABLE properties_definition RENAME TO properties_definition_backup;

        CREATE TABLE properties_definition (
            property_id TEXT PRIMARY KEY,
            property_name TEXT,
            description TEXT,
            wikidata_url TEXT,
            table_name TEXT,
            column_name TEXT
        );

        INSERT INTO properties_definition
            (property_id, property_name, description, wikidata_url, table_name, column_name)
        SELECT
            property_id, property_name, description, wikidata_url, table_name, column_name
        FROM properties_definition_backup;

        DROP TABLE properties_definition_backup;
        """
    )
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM properties_definition").fetchone()[0]
    cols_after = [r[1] for r in conn.execute("PRAGMA table_info(properties_definition)").fetchall()]
    log(f"[14] Properties definition: {total} rows, columns: {', '.join(cols_after)}")
    log("=== Step 14 complete ===")


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db_path) as seed:
            seed.execute(
                "CREATE TABLE properties_definition ("
                "property_id TEXT PRIMARY KEY, property_name TEXT, "
                "description TEXT, wikidata_url TEXT, used_for TEXT, "
                "table_name TEXT, column_name TEXT)"
            )
            insert_rows(seed, "properties_definition", [
                {"property_id": "P21", "property_name": "sex or gender",
                 "description": "biological sex", "wikidata_url": None,
                 "used_for": "gender", "table_name": "individuals", "column_name": "gender"},
                {"property_id": "P31", "property_name": "instance of",
                 "description": None, "wikidata_url": None,
                 "used_for": "instance_of", "table_name": "occupations", "column_name": "instance_of"},
            ])
            seed.commit()

        with open_db(db_path) as conn:
            run(conn)
            rows = conn.execute(
                "SELECT property_id, property_name, table_name, column_name "
                "FROM properties_definition"
            ).fetchall()
            cols = [r[1] for r in conn.execute("PRAGMA table_info(properties_definition)").fetchall()]
        log(f"[sample] columns now: {cols}")
        for r in rows:
            log(f"  properties_definition: {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
