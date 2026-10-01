"""Helper — probe key tables when sqlite_master is suspect.

Mirrors `enhance_db/src/bin/fix_schema.rs`. Read-only diagnostic that
lists what's reachable from sqlite_master and tries direct row counts
on a hard-coded list of expected tables.

Usage
-----
    python3 helper_fix_schema.py
    python3 helper_fix_schema.py --full
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import insert_rows, log, open_db, parse_run_mode

EXPECTED = [
    "individuals", "individuals_keys", "individuals_cliopatria",
    "individuals_countries", "individuals_regions", "consolidate",
    "polities_cliopatria", "properties_definition", "occupations",
    "cities", "nationalities",
]


def run(conn: sqlite3.Connection) -> None:
    log("[helper] fix_schema: probing tables...")
    try:
        rows = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table'"
        ).fetchall()
        log(f"  {len(rows)} tables in sqlite_master")
        for name, sql in rows:
            preview = (sql or "")[:60]
            log(f"    {name} -> {preview}")
    except sqlite3.Error as e:
        log(f"  sqlite_master read failed: {e}")
    for t in EXPECTED:
        try:
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            log(f"  {t}: {n} rows")
        except sqlite3.Error as e:
            log(f"  {t}: ERROR {e}")


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute("CREATE TABLE individuals (wikidata_id TEXT)")
            insert_rows(seed, "individuals", [{"wikidata_id": "Q1"}])
        with open_db(db) as conn:
            run(conn)


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
