#!/usr/bin/env python3
"""Update consolidate table to reflect changes in individuals_cliopatria:
1. Delete consolidate rows for individuals no longer in individuals_cliopatria
2. Update impact_year from individuals_cliopatria.impact_date
"""

import sqlite3
import time

DB_PATH = "/workspace/data/humans_clean.sqlite3"
TASK_LOG = "/workspace/task.log"

def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(TASK_LOG, "a") as f:
        f.write(line + "\n")

def main():
    log("=== Update consolidate table ===")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-2000000")
    conn.execute("PRAGMA busy_timeout=60000")

    # Step 1: Delete orphaned consolidate rows
    log("[1/3] Deleting consolidate rows not in individuals_cliopatria...")
    before = conn.execute("SELECT COUNT(*) FROM consolidate").fetchone()[0]
    conn.execute("""
        DELETE FROM consolidate
        WHERE wikidata_id NOT IN (SELECT wikidata_id FROM individuals_cliopatria)
    """)
    conn.commit()
    after = conn.execute("SELECT COUNT(*) FROM consolidate").fetchone()[0]
    log(f"    Deleted {before - after:,} rows (was {before:,}, now {after:,})")

    # Step 2: Update impact_year from individuals_cliopatria
    log("[2/3] Updating impact_year in consolidate from individuals_cliopatria...")
    updated = conn.execute("""
        UPDATE consolidate SET impact_year = (
            SELECT ic.impact_date FROM individuals_cliopatria ic
            WHERE ic.wikidata_id = consolidate.wikidata_id
        )
        WHERE EXISTS (
            SELECT 1 FROM individuals_cliopatria ic
            WHERE ic.wikidata_id = consolidate.wikidata_id
            AND COALESCE(ic.impact_date, -99999) != COALESCE(consolidate.impact_year, -99999)
        )
    """).rowcount
    conn.commit()
    log(f"    Updated impact_year for {updated:,} rows")

    # Step 3: Verify and stats
    log("[3/3] Final statistics...")
    total = conn.execute("SELECT COUNT(*) FROM consolidate").fetchone()[0]
    with_year = conn.execute("SELECT COUNT(*) FROM consolidate WHERE impact_year IS NOT NULL").fetchone()[0]
    without_year = conn.execute("SELECT COUNT(*) FROM consolidate WHERE impact_year IS NULL").fetchone()[0]
    log(f"    Total consolidate rows: {total:,}")
    log(f"    With impact_year: {with_year:,}")
    log(f"    Without impact_year: {without_year:,}")

    # Cross-check with individuals_cliopatria
    ic_total = conn.execute("SELECT COUNT(*) FROM individuals_cliopatria").fetchone()[0]
    log(f"    individuals_cliopatria total: {ic_total:,}")
    match = "OK" if total == ic_total else "MISMATCH"
    log(f"    consolidate vs individuals_cliopatria: [{match}]")

    conn.close()
    log("=== Update consolidate complete ===")

if __name__ == "__main__":
    main()
