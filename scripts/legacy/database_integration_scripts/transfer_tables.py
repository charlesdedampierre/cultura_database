#!/usr/bin/env python3
"""Transfer properties_definition, individuals_regions, and consolidate
from corrupted database to clean database."""

import sqlite3
import os
import time

CLEAN_DB = "/workspace/data/humans_clean.sqlite3"
CORRUPTED_DB = "/workspace/data/humans_clean_corrputed.sqlite3"
TASK_LOG = "/workspace/task.log"

def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(TASK_LOG, "a") as f:
        f.write(line + "\n")

def main():
    log("=== Transfer tables from corrupted to clean database ===")
    log(f"Clean DB: {CLEAN_DB}")
    log(f"Corrupted DB: {CORRUPTED_DB}")

    conn = sqlite3.connect(CLEAN_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-2000000")
    conn.execute("PRAGMA busy_timeout=60000")

    # Attach corrupted database
    conn.execute(f"ATTACH DATABASE '{CORRUPTED_DB}' AS corrupted")
    log("Attached corrupted database")

    # === 1. Transfer properties_definition ===
    log("[1] Transferring properties_definition...")
    start = time.time()
    conn.execute("DROP TABLE IF EXISTS main.properties_definition")
    # Get the CREATE TABLE statement from corrupted
    create_sql = conn.execute(
        "SELECT sql FROM corrupted.sqlite_master WHERE type='table' AND name='properties_definition'"
    ).fetchone()[0]
    conn.execute(create_sql)
    conn.execute("INSERT INTO main.properties_definition SELECT * FROM corrupted.properties_definition")
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM main.properties_definition").fetchone()[0]
    log(f"    properties_definition: {count} rows transferred ({time.time()-start:.1f}s)")

    # === 2. Transfer individuals_regions ===
    log("[2] Transferring individuals_regions...")
    start = time.time()
    conn.execute("DROP TABLE IF EXISTS main.individuals_regions")
    create_sql = conn.execute(
        "SELECT sql FROM corrupted.sqlite_master WHERE type='table' AND name='individuals_regions'"
    ).fetchone()[0]
    conn.execute(create_sql)
    conn.execute("INSERT INTO main.individuals_regions SELECT * FROM corrupted.individuals_regions")
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM main.individuals_regions").fetchone()[0]
    log(f"    individuals_regions: {count:,} rows transferred ({time.time()-start:.1f}s)")

    # Recreate indexes for individuals_regions
    log("    Creating indexes for individuals_regions...")
    idx_start = time.time()
    for idx_sql in conn.execute(
        "SELECT sql FROM corrupted.sqlite_master WHERE type='index' AND tbl_name='individuals_regions' AND sql IS NOT NULL"
    ).fetchall():
        try:
            conn.execute(idx_sql[0])
        except Exception as e:
            log(f"    Index warning: {e}")
    conn.commit()
    log(f"    Indexes created ({time.time()-idx_start:.1f}s)")

    # === 3. Transfer consolidate ===
    log("[3] Transferring consolidate...")
    start = time.time()
    conn.execute("DROP TABLE IF EXISTS main.consolidate")
    create_sql = conn.execute(
        "SELECT sql FROM corrupted.sqlite_master WHERE type='table' AND name='consolidate'"
    ).fetchone()[0]
    conn.execute(create_sql)
    conn.execute("INSERT INTO main.consolidate SELECT * FROM corrupted.consolidate")
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM main.consolidate").fetchone()[0]
    log(f"    consolidate: {count:,} rows transferred ({time.time()-start:.1f}s)")

    # Recreate indexes for consolidate
    log("    Creating indexes for consolidate...")
    idx_start = time.time()
    for idx_sql in conn.execute(
        "SELECT sql FROM corrupted.sqlite_master WHERE type='index' AND tbl_name='consolidate' AND sql IS NOT NULL"
    ).fetchall():
        try:
            conn.execute(idx_sql[0])
        except Exception as e:
            log(f"    Index warning: {e}")
    conn.commit()
    log(f"    Indexes created ({time.time()-idx_start:.1f}s)")

    # === 4. Verification ===
    log("[4] Verification...")
    for table in ['properties_definition', 'individuals_regions', 'consolidate']:
        src = conn.execute(f"SELECT COUNT(*) FROM corrupted.{table}").fetchone()[0]
        dst = conn.execute(f"SELECT COUNT(*) FROM main.{table}").fetchone()[0]
        status = "OK" if src == dst else "MISMATCH!"
        log(f"    {table}: corrupted={src:,} clean={dst:,} [{status}]")

    conn.execute("DETACH DATABASE corrupted")
    conn.close()
    log("=== Transfer complete ===")

if __name__ == "__main__":
    main()
