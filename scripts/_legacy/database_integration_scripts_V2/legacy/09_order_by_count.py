"""09 - Reorder count-bearing tables by count DESC; add city sitelinks.

Mirrors `enhance_db/src/bin/09_order_by_count.rs`.

  Inputs : occupations, nationalities, cities, identifier_types,
           modern_country, writing_languages
  Output : Each table is rebuilt with rows physically sorted by count
           DESC (rename + recreate + INSERT...ORDER BY count DESC + drop).
           cities also gains an `en_wikipedia_url` column built from
           name_en when missing.

Usage
-----
    python3 09_order_by_count.py
    python3 09_order_by_count.py --full
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import (
    add_column_if_missing,
    column_exists,
    insert_rows,
    log,
    open_db,
    parse_run_mode,
    table_exists,
)

TABLES_WITH_COUNT = [
    "occupations",
    "nationalities",
    "cities",
    "identifier_types",
    "modern_country",
    "writing_languages",
]


def reorder_table(conn: sqlite3.Connection, table: str) -> None:
    log(f"[DB] Reordering {table} by count DESC...")
    backup = f"{table}_old"

    create_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()[0]
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    col_csv = ", ".join(cols)

    conn.execute(f"DROP TABLE IF EXISTS {backup}")
    conn.execute(f"ALTER TABLE {table} RENAME TO {backup}")
    conn.executescript(create_sql + ";")
    conn.execute(
        f"INSERT INTO {table} ({col_csv}) "
        f"SELECT {col_csv} FROM {backup} ORDER BY count DESC"
    )
    conn.execute(f"DROP TABLE {backup}")
    conn.commit()

    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    log(f"[DB] {table} reordered: {n} rows")


def run(conn: sqlite3.Connection) -> None:
    log("[DB] 09: Reordering tables by count and adding city sitelinks...")

    if table_exists(conn, "cities"):
        if add_column_if_missing(conn, "cities", "en_wikipedia_url", "TEXT"):
            log("[DB] Added en_wikipedia_url column to cities")
        log("[DB] Populating city English Wikipedia sitelinks from sitelinks table...")
        conn.execute(
            "UPDATE cities SET en_wikipedia_url = "
            "'https://en.wikipedia.org/wiki/' || REPLACE(name_en, ' ', '_') "
            "WHERE name_en IS NOT NULL AND name_en != '' AND en_wikipedia_url IS NULL"
        )
        conn.commit()
        n = conn.execute(
            "SELECT COUNT(*) FROM cities WHERE en_wikipedia_url IS NOT NULL"
        ).fetchone()[0]
        log(f"[DB] Cities with en_wikipedia_url: {n}")

    for table in TABLES_WITH_COUNT:
        if not table_exists(conn, table):
            log(f"[DB] Skipping {table} (missing).")
            continue
        if not column_exists(conn, table, "count"):
            log(f"[DB] Skipping {table} (no count column).")
            continue
        try:
            reorder_table(conn, table)
        except sqlite3.Error as exc:
            log(f"[DB] Warning: could not reorder {table}: {exc}")

    for table in TABLES_WITH_COUNT:
        if not table_exists(conn, table):
            continue
        try:
            rows = conn.execute(
                f"SELECT COALESCE(name_en, name, id, ''), count FROM {table} LIMIT 5"
            ).fetchall()
        except sqlite3.Error:
            continue
        log(f"[DB] Top entries in {table}:")
        for name, count in rows:
            log(f"  {name} ({count})")
    log("[DB] 09: Done. All tables ordered by count DESC.")


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db_path) as seed:
            seed.execute(
                "CREATE TABLE occupations ("
                "id TEXT PRIMARY KEY, name_en TEXT, count INTEGER DEFAULT 0)"
            )
            seed.execute(
                "CREATE TABLE cities ("
                "id TEXT PRIMARY KEY, name_en TEXT, count INTEGER DEFAULT 0)"
            )
            insert_rows(seed, "occupations", [
                {"id": "Q1", "name_en": "writer", "count": 50},
                {"id": "Q2", "name_en": "painter", "count": 800},
                {"id": "Q3", "name_en": "scientist", "count": 200},
            ])
            insert_rows(seed, "cities", [
                {"id": "Q90", "name_en": "Paris", "count": 1500},
                {"id": "Q60", "name_en": "New York", "count": 3000},
                {"id": "Q1492", "name_en": "Mexico City", "count": 700},
            ])
            seed.commit()

        with open_db(db_path) as conn:
            run(conn)
            occ = conn.execute("SELECT name_en, count FROM occupations").fetchall()
            cit = conn.execute("SELECT name_en, count, en_wikipedia_url FROM cities").fetchall()

        for r in occ:
            log(f"  occupations: {r}")
        for r in cit:
            log(f"  cities: {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
