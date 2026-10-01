"""63 — Populate individuals.number_of_works from the works table.

Mirrors `enhance_db/src/bin/63_add_number_of_works.rs`.

  number_of_works = COUNT(DISTINCT work_id) per individual_id.
  Individuals with no entries in `works` get 0.

Usage
-----
    python3 63_add_number_of_works.py
    python3 63_add_number_of_works.py --full
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


def run(conn: sqlite3.Connection) -> int:
    log("[DB] 63: Add number_of_works to individuals...")
    add_column_if_missing(
        conn, "individuals", "number_of_works",
        "INTEGER NOT NULL DEFAULT 0",
    )
    conn.execute("UPDATE individuals SET number_of_works = 0")
    n = conn.execute(
        """
        UPDATE individuals
        SET number_of_works = c.n
        FROM (
            SELECT individual_id, COUNT(DISTINCT work_id) AS n
            FROM works GROUP BY individual_id
        ) AS c
        WHERE individuals.wikidata_id = c.individual_id
        """
    ).rowcount
    conn.commit()
    log(f"[DB] populated {n} rows")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_individuals_number_of_works "
        "ON individuals(number_of_works)"
    )
    conn.commit()
    return n


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, name_en TEXT)"
            )
            insert_rows(seed, "individuals", [
                {"wikidata_id": "Q1", "name_en": "Alice"},
                {"wikidata_id": "Q2", "name_en": "Bob"},
                {"wikidata_id": "Q3", "name_en": "Carol"},
            ])
            seed.execute(
                "CREATE TABLE works (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "individual_id TEXT, work_id TEXT, relationship TEXT)"
            )
            insert_rows(seed, "works", [
                {"individual_id": "Q1", "work_id": "W1", "relationship": "P50"},
                {"individual_id": "Q1", "work_id": "W1", "relationship": "P170"},
                {"individual_id": "Q1", "work_id": "W2", "relationship": "P50"},
                {"individual_id": "Q2", "work_id": "W3", "relationship": "P50"},
            ])
        with open_db(db) as conn:
            run(conn)
            for r in conn.execute(
                "SELECT wikidata_id, name_en, number_of_works FROM individuals"
            ):
                log(f"  {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
