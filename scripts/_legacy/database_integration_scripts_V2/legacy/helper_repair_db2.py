"""Helper — repair "database disk image is malformed" caused by orphan WAL.

Mirrors `enhance_db/src/bin/repair_db2.rs` (Phase A + verify only — the
header-byte patching from Phase C is left as a manual step).

Switches journal_mode WAL -> DELETE, removes orphan WAL/SHM files, then
runs PRAGMA integrity_check(1) on the result.

Usage
-----
    python3 helper_repair_db2.py
    python3 helper_repair_db2.py --full
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

from common import DB_PATH, log, parse_run_mode


def remove_orphaned_wal(db_path: Path) -> None:
    wal = Path(f"{db_path}-wal")
    shm = Path(f"{db_path}-shm")
    if wal.exists() and wal.stat().st_size == 0:
        log(f"  removing empty WAL: {wal}")
        wal.unlink()
    if shm.exists() and not wal.exists():
        log(f"  removing orphaned SHM: {shm}")
        shm.unlink()


def run(db_path: Path = DB_PATH) -> bool:
    log(f"[helper] repair_db2: switching {db_path} to DELETE journal mode")
    remove_orphaned_wal(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        old = conn.execute("PRAGMA journal_mode").fetchone()[0]
        log(f"  journal_mode was: {old}")
        try:
            for r in conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall():
                log(f"  checkpoint -> {r}")
        except sqlite3.Error as e:
            log(f"  checkpoint failed: {e}")
        new = conn.execute("PRAGMA journal_mode = DELETE").fetchone()[0]
        log(f"  journal_mode now: {new}")
    finally:
        conn.close()
    remove_orphaned_wal(db_path)

    log("  verifying...")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )]
        log(f"  tables: {len(names)}")
        result = conn.execute("PRAGMA integrity_check(1)").fetchone()[0]
        log(f"  integrity_check(1): {result}")
        return result == "ok"
    finally:
        conn.close()


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute("CREATE TABLE t (x INTEGER)")
            seed.execute("INSERT INTO t VALUES (1)")
            seed.execute("PRAGMA journal_mode=WAL")
        run(db)


if __name__ == "__main__":
    if parse_run_mode() == "full":
        run()
    else:
        _sample_main()
