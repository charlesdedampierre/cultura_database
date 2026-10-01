#!/usr/bin/env python3
"""
Equivalent of: sqlite3 corrupt.db ".recover" | sqlite3 new.db
Uses Python's sqlite3.Connection.iterdump() to stream SQL from the source
and execute it into a fresh database. This bypasses corruption by reading
what's readable and writing clean SQL.
"""

import sqlite3
import os
import time
import sys

SRC_DB = "/workspace/data/humans_clean.sqlite3"
DST_DB = "/workspace/data/humans_clean_new.sqlite3"

def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)

def elapsed(start):
    s = int(time.time() - start)
    if s < 60:
        return f"{s}s"
    elif s < 3600:
        return f"{s // 60}m {s % 60}s"
    else:
        return f"{s // 3600}h {(s % 3600) // 60}m {s % 60}s"

def main():
    total_start = time.time()
    log("=== RECOVER: streaming dump from corrupt DB into clean DB ===")
    log(f"Source: {SRC_DB}")
    log(f"Destination: {DST_DB}")

    # Remove destination if it exists
    for path in [DST_DB, DST_DB + "-wal", DST_DB + "-shm"]:
        if os.path.exists(path):
            os.remove(path)

    # Open source (read-only to avoid further corruption)
    src = sqlite3.connect(f"file:{SRC_DB}?mode=ro", uri=True)
    src.execute("PRAGMA cache_size=-2000000;")

    # Open destination
    dst = sqlite3.connect(DST_DB)
    dst.execute("PRAGMA journal_mode=WAL;")
    dst.execute("PRAGMA synchronous=OFF;")
    dst.execute("PRAGMA cache_size=-2000000;")

    log("Streaming iterdump()...")
    count = 0
    errors = 0
    last_report = time.time()

    try:
        for sql in src.iterdump():
            try:
                dst.execute(sql)
                count += 1
                if time.time() - last_report > 30:
                    log(f"  ... {count:,} statements executed ({elapsed(total_start)})")
                    last_report = time.time()
            except Exception as e:
                errors += 1
                if errors <= 20:
                    log(f"  ERROR on statement {count}: {e}")
                    log(f"    SQL: {sql[:200]}...")
    except Exception as e:
        log(f"  iterdump() error after {count:,} statements: {e}")

    dst.commit()
    log(f"Dump complete: {count:,} statements, {errors} errors ({elapsed(total_start)})")

    # Verify tables
    log("--- Verification ---")
    src_tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()}
    dst_tables = {r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()}

    for name in sorted(src_tables):
        try:
            sc = src.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        except:
            sc = "ERROR"
        if name in dst_tables:
            dc = dst.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            status = "OK" if sc == dc else "MISMATCH"
        else:
            dc = "MISSING"
            status = "MISSING"
        log(f"  {name}: src={sc:,} dst={dc} [{status}]" if isinstance(sc, int) and isinstance(dc, int) else f"  {name}: src={sc} dst={dc} [{status}]")

    src.close()

    # Integrity check
    log("Running integrity check...")
    integrity = dst.execute("PRAGMA integrity_check;").fetchone()[0]
    log(f"Integrity: {integrity}")

    dst.close()

    size_mb = os.path.getsize(DST_DB) / (1024 * 1024)
    log(f"New database size: {size_mb:.1f} MB")
    log(f"=== RECOVER COMPLETE ({elapsed(total_start)}) ===")
    log(f"Clean database at: {DST_DB}")

if __name__ == "__main__":
    main()
