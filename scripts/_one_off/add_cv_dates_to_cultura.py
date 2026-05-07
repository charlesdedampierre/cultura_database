"""Add birthdate_from_CV and deathdate_from_CV columns to individuals.

- Loads CV CSV via DuckDB.
- Stages (qid, birth, death) into a SQLite temp table.
- Adds the two columns to individuals (idempotent).
- Benchmarks an UPDATE on a 10k sample, then runs the full UPDATE FROM.

Year is stored as TEXT (e.g. '1932', '-450') to align with existing TEXT date columns.
"""

from __future__ import annotations
import sqlite3
import time
from pathlib import Path

import duckdb
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
CV_CSV = ROOT / "data/similar_databases/cross-verified-database/cross-verified-database.utf8.csv.gz"
DB = ROOT / "data/humans_clean.sqlite3"

BATCH = 50_000


def load_cv_pairs() -> list[tuple[str, str | None, str | None]]:
    """Return [(qid, birth_year_str|None, death_year_str|None), ...] from CV."""
    con = duckdb.connect()
    rows = con.execute(
        f"""
        SELECT
            wikidata_code,
            CASE WHEN TRY_CAST(birth AS INTEGER) IS NOT NULL
                 THEN CAST(TRY_CAST(birth AS INTEGER) AS VARCHAR) END,
            CASE WHEN TRY_CAST(death AS INTEGER) IS NOT NULL
                 THEN CAST(TRY_CAST(death AS INTEGER) AS VARCHAR) END
        FROM read_csv_auto('{CV_CSV}', header=true, ignore_errors=true)
        WHERE wikidata_code IS NOT NULL AND wikidata_code <> '';
        """
    ).fetchall()
    con.close()
    return rows


def column_exists(cur: sqlite3.Cursor, table: str, col: str) -> bool:
    cur.execute(f"PRAGMA table_info({table});")
    return any(r[1] == col for r in cur.fetchall())


def main() -> None:
    t0 = time.perf_counter()

    print("[1/6] Loading CV (qid, birth, death) via DuckDB...")
    pairs = load_cv_pairs()
    print(f"      loaded {len(pairs):,} rows in {time.perf_counter()-t0:.1f}s")

    print(f"[2/6] Connecting to {DB} ...")
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = NORMAL;")
    cur.execute("PRAGMA temp_store = MEMORY;")
    cur.execute("PRAGMA cache_size = -2000000;")  # ~2 GB page cache

    print("[3/6] Adding columns (if missing)...")
    if not column_exists(cur, "individuals", "birthdate_from_CV"):
        cur.execute("ALTER TABLE individuals ADD COLUMN birthdate_from_CV TEXT;")
        print("      added birthdate_from_CV")
    else:
        print("      birthdate_from_CV already exists")
    if not column_exists(cur, "individuals", "deathdate_from_CV"):
        cur.execute("ALTER TABLE individuals ADD COLUMN deathdate_from_CV TEXT;")
        print("      added deathdate_from_CV")
    else:
        print("      deathdate_from_CV already exists")
    con.commit()

    print("[4/6] Building temp table cv_dates and bulk-inserting...")
    cur.execute("DROP TABLE IF EXISTS cv_dates;")
    cur.execute(
        "CREATE TEMP TABLE cv_dates ("
        "qid TEXT PRIMARY KEY, birth TEXT, death TEXT) WITHOUT ROWID;"
    )
    t = time.perf_counter()
    with con:
        for i in tqdm(range(0, len(pairs), BATCH), desc="insert cv_dates"):
            chunk = pairs[i : i + BATCH]
            cur.executemany(
                "INSERT OR REPLACE INTO cv_dates(qid, birth, death) VALUES (?, ?, ?);",
                chunk,
            )
    print(f"      cv_dates built in {time.perf_counter()-t:.1f}s")

    print("[5/6] Bench: UPDATE on a 10k sample...")
    cur.execute(
        "CREATE TEMP TABLE bench_qids AS SELECT qid FROM cv_dates LIMIT 10000;"
    )
    cur.execute("CREATE INDEX bench_idx ON bench_qids(qid);")
    t = time.perf_counter()
    cur.execute(
        """
        UPDATE individuals
           SET birthdate_from_CV = (SELECT birth FROM cv_dates WHERE qid = individuals.wikidata_id),
               deathdate_from_CV = (SELECT death FROM cv_dates WHERE qid = individuals.wikidata_id)
         WHERE wikidata_id IN (SELECT qid FROM bench_qids);
        """
    )
    con.commit()
    bench = time.perf_counter() - t
    n_full = cur.execute("SELECT COUNT(*) FROM cv_dates;").fetchone()[0]
    est = bench * (n_full / 10_000)
    print(f"      10k rows in {bench:.2f}s  →  full UPDATE est. ~{est/60:.1f} min")

    # Reset the bench rows so the full UPDATE produces clean numbers
    cur.execute(
        """
        UPDATE individuals
           SET birthdate_from_CV = NULL, deathdate_from_CV = NULL
         WHERE wikidata_id IN (SELECT qid FROM bench_qids);
        """
    )
    con.commit()

    print(f"[6/6] Running full UPDATE on {n_full:,} matched individuals...")
    t = time.perf_counter()
    cur.execute(
        """
        UPDATE individuals
           SET birthdate_from_CV = (SELECT birth FROM cv_dates WHERE qid = individuals.wikidata_id),
               deathdate_from_CV = (SELECT death FROM cv_dates WHERE qid = individuals.wikidata_id)
         WHERE wikidata_id IN (SELECT qid FROM cv_dates);
        """
    )
    con.commit()
    print(f"      full UPDATE finished in {(time.perf_counter()-t)/60:.1f} min")

    print("\nVerification:")
    n_b = cur.execute(
        "SELECT COUNT(*) FROM individuals WHERE birthdate_from_CV IS NOT NULL;"
    ).fetchone()[0]
    n_d = cur.execute(
        "SELECT COUNT(*) FROM individuals WHERE deathdate_from_CV IS NOT NULL;"
    ).fetchone()[0]
    n_b_fill = cur.execute(
        "SELECT COUNT(*) FROM individuals "
        "WHERE birthdate_from_CV IS NOT NULL "
        "  AND (birthdate IS NULL OR birthdate = '');"
    ).fetchone()[0]
    n_d_fill = cur.execute(
        "SELECT COUNT(*) FROM individuals "
        "WHERE deathdate_from_CV IS NOT NULL "
        "  AND (deathdate IS NULL OR deathdate = '');"
    ).fetchone()[0]
    print(f"  individuals with birthdate_from_CV : {n_b:>10,}")
    print(f"  individuals with deathdate_from_CV : {n_d:>10,}")
    print(f"  ↳ where Cultura birthdate is NULL  : {n_b_fill:>10,}  (true gap fills)")
    print(f"  ↳ where Cultura deathdate is NULL  : {n_d_fill:>10,}  (true gap fills)")

    con.close()
    print(f"\nTotal wall-clock: {(time.perf_counter()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
