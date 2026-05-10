"""Helper — repair individuals_countries by copying through a temp table.

Mirrors `enhance_db/src/bin/fix_db.rs`. Tries WAL checkpoint, integrity
check, then COPY -> DROP -> RENAME via a temp table.

Usage
-----
    python3 helper_fix_db.py
    python3 helper_fix_db.py --full
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import insert_rows, log, open_db, parse_run_mode


def run(conn: sqlite3.Connection) -> None:
    log("[helper] fix_db: starting...")
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        log("  WAL checkpoint OK")
    except sqlite3.Error as e:
        log(f"  WAL checkpoint failed: {e}")

    log("  integrity_check(10):")
    try:
        for (msg,) in conn.execute("PRAGMA integrity_check(10)").fetchall():
            log(f"    {msg}")
    except sqlite3.Error as e:
        log(f"    error: {e}")

    log("  rebuilding individuals_countries via tmp table...")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS individuals_countries_tmp (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            iso_country_name TEXT,
            iso_a3_code TEXT,
            origins TEXT
        )
        """
    )
    try:
        n = conn.execute(
            "INSERT OR IGNORE INTO individuals_countries_tmp "
            "SELECT * FROM individuals_countries"
        ).rowcount
        log(f"    copied {n} rows")
    except sqlite3.Error as e:
        log(f"    copy failed: {e}")
    try:
        conn.execute("DROP TABLE IF EXISTS individuals_countries")
        conn.execute(
            "ALTER TABLE individuals_countries_tmp RENAME TO individuals_countries"
        )
        log("    swap OK")
    except sqlite3.Error as e:
        log(f"    swap failed: {e}")
    conn.commit()
    try:
        n = conn.execute("SELECT COUNT(*) FROM individuals_countries").fetchone()[0]
        log(f"  individuals_countries final: {n}")
    except sqlite3.Error as e:
        log(f"  verify failed: {e}")


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE individuals_countries (wikidata_id TEXT PRIMARY KEY, "
                "name_en TEXT, iso_country_name TEXT, iso_a3_code TEXT, origins TEXT)"
            )
            insert_rows(seed, "individuals_countries", [
                {"wikidata_id": "Q1", "name_en": "Alice",
                 "iso_country_name": "France", "iso_a3_code": "FRA",
                 "origins": "nationality"},
            ])
        with open_db(db) as conn:
            run(conn)


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
