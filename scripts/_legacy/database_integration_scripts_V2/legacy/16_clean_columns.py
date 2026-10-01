"""16 — Drop unused columns from cities, occupations, properties_definition.

Mirrors `enhance_db/src/bin/16_clean_columns.rs`.

  Inputs : existing tables cities, occupations, properties_definition
  Output : cities loses `count`; occupations loses `instance_of_id` and
           `instance_of`; properties_definition loses `wikidata_url`.

Usage
-----
    python3 16_clean_columns.py
    python3 16_clean_columns.py --full
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import (
    DB_PATH,
    column_exists,
    insert_rows,
    log,
    open_db,
    parse_run_mode,
)


def _drop_column_if_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    if not column_exists(conn, table, column):
        return False
    conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    conn.commit()
    return True


def run(conn: sqlite3.Connection) -> None:
    log("[DB] 16: Cleaning columns from cities, occupations, properties_definition...")

    log("[16] Removing 'count' from cities...")
    conn.execute("DROP INDEX IF EXISTS idx_cities_count")
    _drop_column_if_exists(conn, "cities", "count")
    n = conn.execute("SELECT COUNT(*) FROM cities").fetchone()[0]
    log(f"[16] Cities: {n} rows, count column removed")

    log("[16] Removing 'instance_of_id' and 'instance_of' from occupations...")
    _drop_column_if_exists(conn, "occupations", "instance_of_id")
    _drop_column_if_exists(conn, "occupations", "instance_of")
    n = conn.execute("SELECT COUNT(*) FROM occupations").fetchone()[0]
    log(f"[16] Occupations: {n} rows, instance_of columns removed")

    log("[16] Removing 'wikidata_url' from properties_definition...")
    _drop_column_if_exists(conn, "properties_definition", "wikidata_url")
    n = conn.execute("SELECT COUNT(*) FROM properties_definition").fetchone()[0]
    log(f"[16] Properties definition: {n} rows, wikidata_url removed")

    log("[16] Done.")


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE cities (id TEXT PRIMARY KEY, name_en TEXT, count INTEGER)"
            )
            seed.execute(
                "CREATE TABLE occupations (id TEXT PRIMARY KEY, name_en TEXT, "
                "instance_of_id TEXT, instance_of TEXT)"
            )
            seed.execute(
                "CREATE TABLE properties_definition (id TEXT PRIMARY KEY, "
                "name TEXT, wikidata_url TEXT)"
            )
            insert_rows(seed, "cities", [
                {"id": "Q90", "name_en": "Paris", "count": 100},
                {"id": "Q60", "name_en": "New York", "count": 200},
            ])
            insert_rows(seed, "occupations", [
                {"id": "Q1", "name_en": "writer", "instance_of_id": "Q12", "instance_of": "profession"},
            ])
            insert_rows(seed, "properties_definition", [
                {"id": "P31", "name": "instance of", "wikidata_url": "https://example/P31"},
            ])

        with open_db(db) as conn:
            run(conn)
            log(f"[sample] cities cols: {[r[1] for r in conn.execute('PRAGMA table_info(cities)').fetchall()]}")
            log(f"[sample] occupations cols: {[r[1] for r in conn.execute('PRAGMA table_info(occupations)').fetchall()]}")
            log(f"[sample] properties_definition cols: {[r[1] for r in conn.execute('PRAGMA table_info(properties_definition)').fetchall()]}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db(DB_PATH) as conn:
            run(conn)
    else:
        _sample_main()
