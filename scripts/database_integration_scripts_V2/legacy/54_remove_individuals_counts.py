"""54 — Drop polities_cliopatria.individuals_count column.

Mirrors `enhance_db/src/bin/54_remove_individuals_counts.rs`.

Keeps `number_individuals`. Requires SQLite >= 3.35 for ALTER TABLE DROP COLUMN.

Usage
-----
    python3 54_remove_individuals_counts.py
    python3 54_remove_individuals_counts.py --full
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import column_exists, insert_rows, log, open_db, parse_run_mode


def run(conn: sqlite3.Connection) -> None:
    log("[DB] 54: drop polities_cliopatria.individuals_count")
    if column_exists(conn, "polities_cliopatria", "individuals_count"):
        conn.execute("ALTER TABLE polities_cliopatria DROP COLUMN individuals_count")
        conn.commit()
        log("[DB] dropped individuals_count")
    else:
        log("[DB] column missing, nothing to do")
    sch = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='polities_cliopatria'"
    ).fetchone()
    log(f"[DB] schema now: {sch[0] if sch else None}")


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE polities_cliopatria (id INTEGER PRIMARY KEY, "
                "name TEXT, individuals_count INTEGER, "
                "number_individuals INTEGER)"
            )
            insert_rows(seed, "polities_cliopatria", [
                {"id": 1, "name": "Han", "individuals_count": 100,
                 "number_individuals": 90},
            ])
        with open_db(db) as conn:
            run(conn)
            cols = [r[1] for r in conn.execute("PRAGMA table_info(polities_cliopatria)")]
            log(f"[sample] columns now: {cols}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
