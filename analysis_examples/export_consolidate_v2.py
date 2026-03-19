"""
Export consolidate_v2.csv using individuals_impact_date for impact years
instead of individuals_cliopatria.impact_date.

Joins consolidate table (has is_scientist/is_artist flags) with
individuals_impact_date (has full impact dates for more individuals).
"""
import sqlite3
import os
import time

DB_PATH = '../data/humans_clean.sqlite3'
CSV_PATH = '../data/consolidate_v2.csv'
TASK_LOG = '../task.log'


def log(msg):
    print(msg)
    with open(TASK_LOG, 'a') as f:
        f.write(msg + '\n')


def csv_escape(field):
    """RFC 4180 CSV escaping, strip control characters."""
    if field is None:
        return ''
    s = str(field)
    # Strip control characters (newlines, tabs, etc.) that break CSV
    s = ''.join(c for c in s if c >= ' ' or c == '')
    if ',' in s or '"' in s or '\n' in s:
        return '"' + s.replace('"', '""') + '"'
    return s


def main():
    if os.path.exists(TASK_LOG):
        os.remove(TASK_LOG)

    start = time.time()
    log("=== Export consolidate_v2.csv (using individuals_impact_date) ===")

    conn = sqlite3.connect(DB_PATH)
    conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
    conn.execute("PRAGMA cache_size=-2000000")

    # Count total rows
    total = conn.execute("SELECT COUNT(*) FROM consolidate").fetchone()[0]
    log(f"Total rows in consolidate: {total:,}")

    # The query: join consolidate with individuals_impact_date to get the full impact year
    query = """
        SELECT
            c.wikidata_id,
            c.name_en,
            CASE
                WHEN iid.impact_date LIKE '-%'
                THEN -CAST(SUBSTR(iid.impact_date, 2, 4) AS INTEGER)
                ELSE CAST(SUBSTR(iid.impact_date, 1, 4) AS INTEGER)
            END as impact_year,
            c.polity_name,
            c.occupations,
            c.gender,
            c.references_count,
            c.is_scientist,
            c.is_artist
        FROM consolidate c
        LEFT JOIN individuals_impact_date iid ON c.wikidata_id = iid.wikidata_id
    """

    log("Running query...")
    cur = conn.execute(query)

    log(f"Writing CSV to {CSV_PATH}...")
    with open(CSV_PATH, 'w', encoding='utf-8') as f:
        # Header
        f.write("wikidata_id,name_en,impact_year,polity_name,occupations,gender,references_count,is_scientist,is_artist\n")

        rows_written = 0
        null_impact_old = 0
        null_impact_new = 0
        gained_impact = 0

        for row in cur:
            wid, name, impact_year, polity, occs, gender, refs, is_sci, is_art = row

            if impact_year is None:
                null_impact_new += 1
            impact_str = str(impact_year) if impact_year is not None else ''

            line = (
                f"{csv_escape(wid)},"
                f"{csv_escape(name)},"
                f"{impact_str},"
                f"{csv_escape(polity)},"
                f"{csv_escape(occs)},"
                f"{csv_escape(gender)},"
                f"{refs if refs is not None else ''},"
                f"{is_sci},"
                f"{is_art}\n"
            )
            f.write(line)
            rows_written += 1

            if rows_written % 1_000_000 == 0:
                elapsed = time.time() - start
                log(f"  {rows_written:,} rows written ({elapsed:.0f}s)")

    elapsed = time.time() - start
    log(f"CSV written: {rows_written:,} rows ({elapsed:.0f}s)")
    log(f"Rows with NULL impact_year: {null_impact_new:,}")

    # Compare with original consolidate
    old_with_impact = conn.execute(
        "SELECT COUNT(*) FROM consolidate WHERE impact_year IS NOT NULL"
    ).fetchone()[0]
    log(f"\nComparison with original consolidate:")
    log(f"  Original impact_year non-NULL: {old_with_impact:,}")
    log(f"  V2 impact_year non-NULL: {rows_written - null_impact_new:,}")
    log(f"  Gained: {(rows_written - null_impact_new) - old_with_impact:,} additional impact years")

    # File size
    size_mb = os.path.getsize(CSV_PATH) / (1024 * 1024)
    log(f"\nFile size: {size_mb:.1f} MB")

    conn.close()
    log(f"\n=== Export complete ({elapsed:.0f}s) ===")


if __name__ == '__main__':
    main()
