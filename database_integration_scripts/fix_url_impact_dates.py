"""
Fix individuals_cliopatria: for URL-matched rows, ensure that individuals
are only linked to a polity when BOTH conditions are met:
  1. The individual has a URL matching the polity
  2. The individual's impact_date falls within the polity's existence period

Steps:
  1. Load polity periods
  2. Find all URL-matched rows (with or without impact_date already set)
  3. Look up impact_date from individuals_impact_date
  4. Validate: keep only rows where impact_date falls within polity period
  5. Delete rows that fail validation (no impact_date, or date outside polity)
  6. Update polities_cliopatria mixed_count
"""
import sqlite3
import os
import time

DB_PATH = "/workspace/data/humans_clean.sqlite3"
TASK_LOG = "/workspace/task.log"

def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(TASK_LOG, "a") as f:
        f.write(line + "\n")

def parse_year(date_str):
    """Parse year from date string like '1980-01-01' or '-0500-01-01'."""
    if not date_str:
        return None
    try:
        if date_str.startswith('-'):
            rest = date_str[1:]
            year_str = rest.split('-')[0]
            return -int(year_str)
        else:
            year_str = date_str.split('-')[0]
            return int(year_str)
    except (ValueError, IndexError):
        return None

def main():
    log("=== Fix URL impact_dates in individuals_cliopatria ===")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-2000000")
    conn.execute("PRAGMA busy_timeout=60000")
    c = conn.cursor()

    # Step 1: Load polity periods (polity_id -> list of (from_year, to_year))
    log("[1/6] Loading polity periods...")
    polity_periods = {}
    c.execute("SELECT polity_id, from_year, to_year FROM cliopatria_polity_periods")
    for pid, from_y, to_y in c.fetchall():
        if pid not in polity_periods:
            polity_periods[pid] = []
        polity_periods[pid].append((from_y, to_y))
    log(f"    Loaded periods for {len(polity_periods)} polities")

    # Step 2: Load impact dates from individuals_impact_date
    log("[2/6] Loading impact dates from individuals_impact_date...")
    impact_dates = {}
    c.execute("SELECT wikidata_id, impact_date FROM individuals_impact_date")
    for wid, date_str in c.fetchall():
        year = parse_year(date_str)
        if year is not None:
            impact_dates[wid] = year
    log(f"    Loaded {len(impact_dates):,} impact dates")

    # Step 3: Get ALL URL-matched rows from individuals_cliopatria
    log("[3/6] Loading all URL-matched rows from individuals_cliopatria...")
    c.execute("""
        SELECT wikidata_id, polity_id, impact_date
        FROM individuals_cliopatria
        WHERE method = 'url'
    """)
    url_rows = c.fetchall()
    log(f"    Found {len(url_rows):,} URL-matched rows")

    # Step 4: Classify each row
    log("[4/6] Classifying URL rows...")
    to_update = []   # (impact_year, wikidata_id) - valid match, set/update impact_date
    to_delete = []   # wikidata_id - invalid match, remove
    stats = {
        "valid_date_match": 0,
        "valid_no_polity_periods": 0,
        "invalid_date_outside": 0,
        "invalid_no_impact_date": 0,
        "invalid_no_parseable_date": 0,
    }

    for wikidata_id, polity_id, existing_impact_date in url_rows:
        # Look up impact_date (prefer individuals_impact_date as source of truth)
        year = impact_dates.get(wikidata_id)

        if year is None:
            # No impact_date available - can't validate date condition
            to_delete.append(wikidata_id)
            stats["invalid_no_impact_date"] += 1
            continue

        # Check if polity has period data
        periods = polity_periods.get(polity_id)
        if periods is None:
            # Polity has no period data - keep the match, set impact_date
            to_update.append((year, wikidata_id))
            stats["valid_no_polity_periods"] += 1
            continue

        # Check if impact_date falls within any polity period
        valid = any(from_y <= year <= to_y for from_y, to_y in periods)
        if valid:
            to_update.append((year, wikidata_id))
            stats["valid_date_match"] += 1
        else:
            to_delete.append(wikidata_id)
            stats["invalid_date_outside"] += 1

    log(f"    Classification results:")
    log(f"      Valid (date within polity period): {stats['valid_date_match']:,}")
    log(f"      Valid (polity has no period data): {stats['valid_no_polity_periods']:,}")
    log(f"      Invalid (date outside all periods): {stats['invalid_date_outside']:,}")
    log(f"      Invalid (no impact_date available): {stats['invalid_no_impact_date']:,}")
    log(f"    Total to UPDATE: {len(to_update):,}")
    log(f"    Total to DELETE: {len(to_delete):,}")

    # Step 5a: Apply updates in batches
    BATCH = 50000

    log("[5/6] Applying changes...")
    log("  [5a] Updating impact_date for valid URL matches...")
    for i in range(0, len(to_update), BATCH):
        batch = to_update[i:i+BATCH]
        conn.execute("BEGIN TRANSACTION")
        c.executemany(
            "UPDATE individuals_cliopatria SET impact_date = ? WHERE wikidata_id = ?",
            batch
        )
        conn.commit()
        done = min(i+BATCH, len(to_update))
        log(f"    Updated {done:,}/{len(to_update):,}")

    # Step 5b: Delete invalid matches in batches
    log("  [5b] Deleting invalid URL matches...")
    for i in range(0, len(to_delete), BATCH):
        batch = to_delete[i:i+BATCH]
        conn.execute("BEGIN TRANSACTION")
        placeholders = ",".join(["?"] * len(batch))
        c.execute(
            f"DELETE FROM individuals_cliopatria WHERE wikidata_id IN ({placeholders})",
            batch
        )
        conn.commit()
        done = min(i+BATCH, len(to_delete))
        log(f"    Deleted {done:,}/{len(to_delete):,}")

    # Step 6: Final stats and update mixed_count
    log("[6/6] Final statistics and mixed_count update...")
    c.execute("""
        SELECT method,
               CASE WHEN impact_date IS NULL THEN 'NULL' ELSE 'SET' END,
               COUNT(*)
        FROM individuals_cliopatria
        GROUP BY method, 2
    """)
    for method, date_status, count in c.fetchall():
        log(f"    method={method}, impact_date={date_status}, count={count:,}")

    c.execute("SELECT COUNT(*) FROM individuals_cliopatria")
    log(f"    Total rows in individuals_cliopatria: {c.fetchone()[0]:,}")

    # Update polities_cliopatria mixed_count
    log("    Updating polities_cliopatria mixed_count...")
    cols = [r[1] for r in c.execute("PRAGMA table_info(polities_cliopatria)").fetchall()]
    if "mixed_count" not in cols:
        conn.execute("ALTER TABLE polities_cliopatria ADD COLUMN mixed_count INTEGER DEFAULT 0")
    conn.execute("UPDATE polities_cliopatria SET mixed_count = 0")
    conn.execute("""
        UPDATE polities_cliopatria SET mixed_count = (
            SELECT COUNT(*) FROM individuals_cliopatria ic
            WHERE ic.polity_name = polities_cliopatria.name
        )
    """)
    conn.commit()

    log("=== Fix URL impact_dates complete ===")
    conn.close()

if __name__ == "__main__":
    main()
