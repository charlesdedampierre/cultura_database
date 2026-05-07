#!/usr/bin/env python3
"""Transfer all tables from corrupted SQLite database to a fresh clean one.
Uses ATTACH DATABASE + INSERT INTO ... SELECT so data never leaves SQLite's engine."""

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
    with open("/workspace/transfer.log", "a") as f:
        f.write(line + "\n")

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
    log("=== TRANSFER: Copying all tables to clean database ===")
    log(f"Source: {SRC_DB}")
    log(f"Destination: {DST_DB}")

    # Remove destination if it exists
    if os.path.exists(DST_DB):
        os.remove(DST_DB)
        log("Removed existing destination database")
    # Also remove WAL/SHM files
    for ext in ["-wal", "-shm"]:
        p = DST_DB + ext
        if os.path.exists(p):
            os.remove(p)

    # Open source database
    conn = sqlite3.connect(SRC_DB)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA cache_size=-4000000;")  # ~4GB cache
    conn.execute("PRAGMA busy_timeout=60000;")
    conn.execute("PRAGMA mmap_size=8589934592;")  # 8GB mmap

    # Attach clean database
    conn.execute(f"ATTACH DATABASE '{DST_DB}' AS clean;")
    conn.execute("PRAGMA clean.journal_mode=WAL;")
    conn.execute("PRAGMA clean.synchronous=OFF;")
    conn.execute("PRAGMA clean.cache_size=-4000000;")
    log("Attached clean database")

    # Get all objects from source
    objects = conn.execute(
        """SELECT type, name, sql FROM main.sqlite_master
           WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
           ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END, name"""
    ).fetchall()

    tables = [(name, sql) for typ, name, sql in objects if typ == "table"]
    indexes = [(name, sql) for typ, name, sql in objects if typ == "index"]

    log(f"Found {len(tables)} tables and {len(indexes)} indexes to transfer")

    # Phase 1: Create tables and copy data
    log("--- Phase 1: Creating tables and copying data ---")
    for name, create_sql in tables:
        step_start = time.time()

        # Create table in clean database
        clean_sql = create_sql.replace("CREATE TABLE ", "CREATE TABLE clean.", 1)
        conn.execute(clean_sql)

        # Copy data
        conn.execute(f'INSERT INTO clean."{name}" SELECT * FROM main."{name}"')
        conn.commit()

        # Get count
        count = conn.execute(f'SELECT COUNT(*) FROM clean."{name}"').fetchone()[0]
        log(f"  {name} : {count:,} rows copied ({elapsed(step_start)})")

    # Phase 2: Create indexes
    log("--- Phase 2: Creating indexes ---")
    for name, create_sql in indexes:
        step_start = time.time()

        # Rewrite to target clean database
        clean_sql = create_sql.replace("CREATE INDEX ", "CREATE INDEX clean.", 1)
        clean_sql = clean_sql.replace("CREATE UNIQUE INDEX ", "CREATE UNIQUE INDEX clean.", 1)

        try:
            conn.execute(clean_sql)
            conn.commit()
            log(f"  Index {name} created ({elapsed(step_start)})")
        except Exception as e:
            log(f"  Index {name} FAILED: {e} ({elapsed(step_start)})")

    # Phase 3: Verify
    log("--- Phase 3: Verification ---")
    all_ok = True
    for name, _ in tables:
        src_count = conn.execute(f'SELECT COUNT(*) FROM main."{name}"').fetchone()[0]
        dst_count = conn.execute(f'SELECT COUNT(*) FROM clean."{name}"').fetchone()[0]
        status = "OK" if src_count == dst_count else "MISMATCH!"
        if src_count != dst_count:
            all_ok = False
        log(f"  {name} : src={src_count:,} dst={dst_count:,} [{status}]")

    # Detach
    conn.execute("DETACH DATABASE clean;")
    conn.close()

    # Run integrity check on new DB
    log("Running integrity check on new database...")
    new_conn = sqlite3.connect(DST_DB)
    integrity = new_conn.execute("PRAGMA integrity_check;").fetchone()[0]
    log(f"New database integrity: {integrity}")

    # Compact: convert WAL to standard journal
    new_conn.execute("PRAGMA journal_mode=DELETE;")
    new_conn.execute("VACUUM;")
    log("Vacuumed new database")
    new_conn.close()

    size_mb = os.path.getsize(DST_DB) / (1024 * 1024)
    log(f"New database size: {size_mb:.1f} MB")
    log(f"=== TRANSFER {'COMPLETE' if all_ok else 'COMPLETED WITH ISSUES'} ({elapsed(total_start)}) ===")
    log(f"Clean database at: {DST_DB}")

    if not all_ok:
        sys.exit(1)

if __name__ == "__main__":
    main()
