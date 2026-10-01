"""28c — Add post-500 CE coverage for Turkey, Romania, Slovenia, Cyprus
(previously only in Ancient Mediterranean), and extend Vatican City,
San Marino, and Malta back to -10000.

Mirrors `enhance_db/src/bin/28c_fix_region_gaps.rs`.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import DB_PATH, log, open_db, parse_run_mode, table_exists, transaction


ADDITIONS: list[tuple[str, str, str, str, int, int | None]] = [
    ("Eastern Europe", "Balkans", "Turkey", "TUR", 500, None),
    ("Eastern Europe", "Balkans", "Romania", "ROU", 500, None),
    ("Eastern Europe", "Balkans", "Slovenia", "SVN", 500, None),
    ("Middle-East and Africa (MENA)", "Arabic world", "Cyprus", "CYP", 500, None),
]


def run(conn: sqlite3.Connection) -> None:
    log("[DB] 28c: Fix region gaps...")
    with transaction(conn):
        cur = conn.cursor()
        inserted = 0
        for row in ADDITIONS:
            cur.execute(
                "INSERT INTO regions (macro_region, region, iso_country_name, iso_a3, "
                "start_year, end_year) VALUES (?, ?, ?, ?, ?, ?)",
                row,
            )
            log(f"[28c] Added {row[2]} ({row[3]}) to {row[0]} / {row[1]} ({row[4]}+)")
            inserted += 1

        cur.execute("UPDATE regions SET start_year = -10000 WHERE iso_a3 = 'VAT'")
        cur.execute("UPDATE regions SET start_year = -10000 WHERE iso_a3 = 'SMR'")
        cur.execute("UPDATE regions SET start_year = -10000 WHERE iso_a3 = 'MLT'")
    log(f"[28c] Inserted {inserted}; extended VAT/SMR/MLT start_year")

    if table_exists(conn, "individuals_countries") and table_exists(conn, "individuals_impact_date"):
        unmapped = conn.execute(
            """
            SELECT ic.iso_country_name, ic.iso_a3_code, COUNT(*)
            FROM individuals_countries ic
            JOIN individuals_impact_date iid ON ic.wikidata_id = iid.wikidata_id
            LEFT JOIN regions r ON ic.iso_a3_code = r.iso_a3
            WHERE r.iso_a3 IS NULL
            GROUP BY ic.iso_country_name
            ORDER BY COUNT(*) DESC
            """
        ).fetchall()
        if unmapped:
            log(f"[28c] Remaining unmapped: {len(unmapped)}")
            for n, iso, c in unmapped:
                log(f"[28c]   {n} ({iso}) -> {c}")
        else:
            log("[28c] No remaining unmapped countries with impact dates")

    total = conn.execute("SELECT COUNT(*) FROM regions").fetchone()[0]
    log(f"[28c] Total regions entries: {total}")


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with open_db(db) as conn:
            conn.execute(
                """
                CREATE TABLE regions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    macro_region TEXT, region TEXT, iso_country_name TEXT,
                    iso_a3 TEXT, start_year INTEGER, end_year INTEGER
                )
                """
            )
            conn.execute(
                "INSERT INTO regions (macro_region, region, iso_country_name, iso_a3, "
                "start_year, end_year) VALUES "
                "('Western Europe', 'Italy', 'Vatican City', 'VAT', 500, NULL),"
                "('Western Europe', 'Italy', 'San Marino', 'SMR', 500, NULL),"
                "('Western Europe', 'Italy', 'Malta', 'MLT', 500, NULL)"
            )
            conn.commit()
            run(conn)
            for row in conn.execute(
                "SELECT iso_a3, start_year FROM regions WHERE iso_a3 IN ('VAT','SMR','MLT','TUR') ORDER BY iso_a3"
            ):
                log(f"  {row}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db(DB_PATH) as conn:
            run(conn)
    else:
        _sample_main()
