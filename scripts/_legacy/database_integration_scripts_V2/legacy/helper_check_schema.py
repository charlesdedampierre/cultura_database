"""Helper — print database schema overview.

Mirrors `enhance_db/src/bin/check_schema.rs`. Read-only diagnostic that
lists tables, key row counts, and the columns of `individuals`.

Usage
-----
    python3 helper_check_schema.py
    python3 helper_check_schema.py --full
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import insert_rows, log, open_db, parse_run_mode


KEY_TABLES = [
    "individuals", "individuals_backup", "sitelinks",
    "identifiers", "cities",
]


def run(conn: sqlite3.Connection) -> None:
    log("[helper] check_schema: listing tables...")
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )]
    log(f"  Tables ({len(tables)}): {tables}")
    for t in KEY_TABLES:
        try:
            n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            log(f"  {t}: {n} rows")
        except sqlite3.Error as e:
            log(f"  {t}: {e}")
    if "individuals" in tables:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(individuals)")]
        log(f"  individuals columns: {cols}")


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, name_en TEXT)"
            )
            insert_rows(seed, "individuals", [
                {"wikidata_id": "Q1", "name_en": "Alice"},
            ])
            seed.execute("CREATE TABLE cities (id TEXT PRIMARY KEY)")
        with open_db(db) as conn:
            run(conn)


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
