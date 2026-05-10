"""02 - Fix mojibake encoding in all text columns.

Mirrors `enhance_db/src/bin/02_fix_encoding.rs`.

  Inputs : data/humans_clean.sqlite3 (in-place updates)
  Output : same DB, with mojibake'd strings repaired across the listed
           tables/columns. Uses `common.fix_mojibake` (Latin-1 -> UTF-8
           round-trip) and processes rows in batches of BATCH_SIZE.

Usage
-----
    python3 02_fix_encoding.py            # tiny synthetic DB
    python3 02_fix_encoding.py --full     # data/humans_clean.sqlite3
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import (
    executemany_batched,
    fix_mojibake,
    insert_rows,
    log,
    open_db,
    parse_run_mode,
    table_exists,
)

BATCH_SIZE = 500_000

# (table, primary-key col, [text columns])
TABLES: list[tuple[str, str, list[str]]] = [
    ("occupations", "id", ["name_en", "meta_occupation", "description_en", "instance_of"]),
    ("nationalities", "name_en", ["description_en", "instance_of"]),
    ("identifier_types", "property_id", ["name_en", "description", "issuer_name", "country_name"]),
    ("properties_definition", "property_id", ["property_name", "description"]),
    ("cities", "id", ["name_en", "country_name", "continent"]),
    ("sitelinks", "id", ["title"]),
    ("identifiers", "wikidata_id", ["individual_name", "identifier_name"]),
    ("individuals", "wikidata_id", [
        "name_en", "description_en", "nationalities_en",
        "birthcity_en", "deathcity_en", "occupations_en",
    ]),
]


def fix_table_column(conn: sqlite3.Connection, table: str, pk: str, col: str) -> int:
    """Stream rows from `table` in BATCH_SIZE pages; UPDATE rows that
    contain mojibake-encoded text. Returns the number of rows fixed."""
    total = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {col} IS NOT NULL"
    ).fetchone()[0]
    if total == 0:
        return 0

    fixes: list[tuple[str, object]] = []
    offset = 0
    while True:
        rows = conn.execute(
            f"SELECT {pk}, {col} FROM {table} "
            f"WHERE {col} IS NOT NULL LIMIT ? OFFSET ?",
            (BATCH_SIZE, offset),
        ).fetchall()
        if not rows:
            break
        for pk_val, text in rows:
            if text is None:
                continue
            fixed = fix_mojibake(text)
            if fixed is not None:
                fixes.append((fixed, pk_val))
        offset += BATCH_SIZE
        if len(rows) < BATCH_SIZE:
            break

    if not fixes:
        return 0

    update_sql = f"UPDATE {table} SET {col} = ? WHERE {pk} = ?"
    executemany_batched(
        conn, update_sql, fixes,
        batch_size=BATCH_SIZE,
        desc=f"{table}.{col}",
        total=len(fixes),
    )
    return len(fixes)


def fix_nationalities_pk(conn: sqlite3.Connection) -> int:
    """The nationalities table uses name_en as PK, so we have to UPDATE
    the PK itself when it's mojibake'd. Skip rows whose fixed value
    would collide with an existing nationality."""
    rows = conn.execute(
        "SELECT name_en FROM nationalities WHERE name_en IS NOT NULL"
    ).fetchall()
    n = 0
    for (name,) in rows:
        fixed = fix_mojibake(name)
        if fixed is None:
            continue
        exists = conn.execute(
            "SELECT 1 FROM nationalities WHERE name_en = ?", (fixed,)
        ).fetchone()
        if exists:
            continue
        conn.execute(
            "UPDATE nationalities SET name_en = ? WHERE name_en = ?",
            (fixed, name),
        )
        log(f"[DB]   Fixed nationality name: '{name}' -> '{fixed}'")
        n += 1
    if n:
        conn.commit()
    return n


def run(conn: sqlite3.Connection) -> int:
    log("[DB] 02: Fixing encoding issues (batched)...")
    total_fixed = 0
    for table, pk, cols in TABLES:
        if not table_exists(conn, table):
            log(f"[DB] Skipping {table} (missing).")
            continue
        for col in cols:
            log(f"[DB] Processing {table}.{col}...")
            try:
                n = fix_table_column(conn, table, pk, col)
            except sqlite3.Error as exc:
                log(f"[DB]   Error fixing {table}.{col}: {exc}")
                continue
            if n:
                log(f"[DB]   Fixed {n} entries in {table}.{col}")
            total_fixed += n

    if table_exists(conn, "nationalities"):
        log("[DB] Fixing nationality name_en (primary key) encoding...")
        total_fixed += fix_nationalities_pk(conn)

    log(f"[DB] 02: Done. Fixed {total_fixed} encoding issues total.")
    return total_fixed


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db_path) as seed:
            seed.execute("CREATE TABLE occupations (id TEXT PRIMARY KEY, name_en TEXT, meta_occupation TEXT, description_en TEXT, instance_of TEXT)")
            seed.execute("CREATE TABLE nationalities (name_en TEXT PRIMARY KEY, description_en TEXT, instance_of TEXT, count INTEGER, wikidata_id TEXT)")
            seed.execute("CREATE TABLE cities (id TEXT PRIMARY KEY, name_en TEXT, country_name TEXT, continent TEXT)")
            mojibake_paris = "Pariès".encode("utf-8").decode("latin-1")  # 'PariÃ¨s'
            mojibake_french = "Français".encode("utf-8").decode("latin-1")
            insert_rows(seed, "occupations", [
                {"id": "Q1", "name_en": mojibake_french, "meta_occupation": None,
                 "description_en": None, "instance_of": None},
                {"id": "Q2", "name_en": "writer", "meta_occupation": None,
                 "description_en": None, "instance_of": None},
            ])
            insert_rows(seed, "nationalities", [
                {"name_en": mojibake_french, "description_en": None,
                 "instance_of": None, "count": 5, "wikidata_id": "Q142"},
            ])
            insert_rows(seed, "cities", [
                {"id": "Q90", "name_en": mojibake_paris, "country_name": None, "continent": None},
            ])
            seed.commit()

        with open_db(db_path) as conn:
            n = run(conn)
            occ = conn.execute("SELECT id, name_en FROM occupations").fetchall()
            nat = conn.execute("SELECT name_en, count FROM nationalities").fetchall()
            cit = conn.execute("SELECT id, name_en FROM cities").fetchall()

        log(f"[sample] fixed {n} mojibake entries")
        for r in occ:
            log(f"  occupations: {r}")
        for r in nat:
            log(f"  nationalities: {r}")
        for r in cit:
            log(f"  cities: {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
