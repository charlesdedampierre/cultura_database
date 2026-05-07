"""Apply the v2 life-expectancy date estimates to `humans_clean.sqlite3`.

- Drops the v1 columns:
    estimated_birthdate_from_life_expectancy
    estimated_deathdate_from_life_expectancy
- Adds new columns (cleaner names):
    birthdate_from_life_expectancy        TEXT (ISO 'YYYY-01-01')
    deathdate_from_life_expectancy        TEXT
    life_expectancy_lookup_source         TEXT  (e.g. 'category+birth_bin:Culture' or 'birth_bin')
    life_expectancy_median_used           REAL  (life-expectancy in years)
- Reads `data/estimated_dates_v2.csv` and UPDATEs each row.

Estimated runtime: ~30-60 s for ~1.3 M updates on a single SQLite file.
Wraps the writes in a single transaction for atomicity. If the script
is interrupted before COMMIT, the table is rolled back to its pre-run
state.

Usage:
    python scripts/_one_off/apply_estimated_dates_v2.py            # dry-run, prints plan
    python scripts/_one_off/apply_estimated_dates_v2.py --commit   # actually writes
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import polars as pl
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "humans_clean.sqlite3"
CSV_PATH = ROOT / "data" / "estimated_dates_v2.csv"

V1_COLS = [
    "estimated_birthdate_from_life_expectancy",
    "estimated_deathdate_from_life_expectancy",
]
V2_COLS = {
    "birthdate_from_life_expectancy": "TEXT",
    "deathdate_from_life_expectancy": "TEXT",
    "life_expectancy_lookup_source": "TEXT",
    "life_expectancy_median_used": "REAL",
}


def existing_columns(cur: sqlite3.Cursor) -> set[str]:
    cur.execute("PRAGMA table_info(individuals)")
    return {r[1] for r in cur.fetchall()}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", type=Path, default=CSV_PATH)
    p.add_argument("--commit", action="store_true",
                   help="actually apply changes (default: dry-run)")
    args = p.parse_args()

    if not args.csv.exists():
        raise SystemExit(f"CSV not found: {args.csv}")

    print(f"Loading estimates from {args.csv.name}...")
    df = pl.read_csv(args.csv).select(
        ["wikidata_id", "est_kind", "est_date", "lookup_source", "median_life_expectancy_used"]
    )
    print(f"  {df.height:,} estimate rows")
    print(f"  est_kind breakdown: {df['est_kind'].value_counts().to_dict(as_series=False)}")

    if not args.commit:
        print("\n[DRY RUN] Plan:")
        print(f"  DROP COLUMN: {', '.join(V1_COLS)}")
        for col, typ in V2_COLS.items():
            print(f"  ADD COLUMN:  {col} {typ}")
        print(f"  UPDATE rows: {df.height:,}")
        print("\nRe-run with --commit to apply.")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("BEGIN")
    try:
        cols = existing_columns(cur)

        # 1) Drop v1 columns (if present)
        for c in V1_COLS:
            if c in cols:
                print(f"DROP COLUMN {c}")
                cur.execute(f"ALTER TABLE individuals DROP COLUMN {c}")

        # 2) Add v2 columns (skip any already present from a prior run)
        cols = existing_columns(cur)
        for col, typ in V2_COLS.items():
            if col not in cols:
                print(f"ADD COLUMN  {col} {typ}")
                cur.execute(f"ALTER TABLE individuals ADD COLUMN {col} {typ}")

        # 3) Bulk-UPDATE in batches of 50k
        sql = """
        UPDATE individuals
        SET birthdate_from_life_expectancy = COALESCE(?, birthdate_from_life_expectancy),
            deathdate_from_life_expectancy = COALESCE(?, deathdate_from_life_expectancy),
            life_expectancy_lookup_source  = ?,
            life_expectancy_median_used    = ?
        WHERE wikidata_id = ?
        """
        rows = df.iter_rows(named=True)
        BATCH = 50_000
        batch: list[tuple] = []
        n_updates = 0
        with tqdm(total=df.height, desc="UPDATE", unit="row") as pbar:
            for r in rows:
                est_birth = r["est_date"] if r["est_kind"] == "birth" else None
                est_death = r["est_date"] if r["est_kind"] == "death" else None
                batch.append((est_birth, est_death,
                              r["lookup_source"], r["median_life_expectancy_used"],
                              r["wikidata_id"]))
                if len(batch) >= BATCH:
                    cur.executemany(sql, batch)
                    n_updates += len(batch)
                    pbar.update(len(batch))
                    batch.clear()
            if batch:
                cur.executemany(sql, batch)
                n_updates += len(batch)
                pbar.update(len(batch))

        cur.execute("COMMIT")
        print(f"\nCommitted. {n_updates:,} UPDATE statements executed.")

        # Quick verification
        cur.execute("SELECT COUNT(*) FROM individuals WHERE birthdate_from_life_expectancy IS NOT NULL")
        n_b = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM individuals WHERE deathdate_from_life_expectancy IS NOT NULL")
        n_d = cur.fetchone()[0]
        print(f"Final counts: birthdate_from_life_expectancy={n_b:,}, deathdate_from_life_expectancy={n_d:,}")
    except Exception:
        cur.execute("ROLLBACK")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
