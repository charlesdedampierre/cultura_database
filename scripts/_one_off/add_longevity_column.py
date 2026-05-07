"""Add `longevity_years` (REAL) to individuals.

Fills it for rows where birthdate and deathdate are both real ISO dates
(not Wikidata blank-node identifiers like `_:bn...`) and both have
precision >= 9 (day-level or finer). BC dates ('-YYYY-MM-DD') are handled.

We use Polars for the computation (loaded into memory once) and write back
in a single UPDATE per row using executemany on a small index. This is fine
for ~3M rows with both dates — runtime ~2-3 minutes.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import polars as pl
from tqdm import tqdm

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "humans_clean.sqlite3"


def parse_year_frac(date_col: str) -> pl.Expr:
    """Parse a Wikidata-style ISO date string into a fractional year.

    Handles BC dates of the form '-YYYY-MM-DD' (sign on year). Uses regex
    extraction so that strings missing the month/day parts simply produce
    null components (filled with 1) instead of an out-of-bounds error.
    Returns null for blank-nodes ('_:bn...') or unparsable strings.
    """
    s = pl.col(date_col)
    is_bc = s.str.starts_with("-")
    # Year: 1-5 digits after the optional leading '-'
    year_str = s.str.extract(r"^-?(\d{1,5})", 1)
    year = year_str.cast(pl.Int64, strict=False)
    # Month / day: optional, default to 1
    month = s.str.extract(r"^-?\d{1,5}-(\d{1,2})", 1).cast(pl.Int64, strict=False).fill_null(1)
    day = s.str.extract(r"^-?\d{1,5}-\d{1,2}-(\d{1,2})", 1).cast(pl.Int64, strict=False).fill_null(1)
    signed_year = pl.when(is_bc).then(-year).otherwise(year)
    # Approximate fractional year: year + (30*(month-1) + (day-1)) / 365
    return (signed_year + (30 * (month - 1) + (day - 1)) / 365.0).alias(
        f"{date_col}_yr"
    )


def main() -> None:
    print(f"DB: {DB_PATH}")
    t0 = time.perf_counter()

    print("Loading birthdate / deathdate columns with Polars...")
    conn = sqlite3.connect(DB_PATH)
    df = pl.read_database(
        """
        SELECT wikidata_id, birthdate, deathdate,
               birthdate_precision, deathdate_precision
        FROM individuals
        WHERE birthdate IS NOT NULL
          AND deathdate IS NOT NULL
          AND birthdate NOT LIKE '\\_:%' ESCAPE '\\'
          AND deathdate NOT LIKE '\\_:%' ESCAPE '\\'
          AND birthdate_precision >= 9
          AND deathdate_precision >= 9
        """,
        conn,
    )
    print(f"  loaded {df.height:,} candidate rows")

    df = df.with_columns([parse_year_frac("birthdate"), parse_year_frac("deathdate")])
    df = df.with_columns(
        (pl.col("deathdate_yr") - pl.col("birthdate_yr"))
        .round(2)
        .alias("longevity_years")
    )
    df = df.filter(
        pl.col("longevity_years").is_not_null()
        & (pl.col("longevity_years") >= 0)
        & (pl.col("longevity_years") <= 130)
    )
    print(f"  {df.height:,} rows with valid longevity in [0, 130]")
    print(df.select("longevity_years").describe())

    cur = conn.cursor()
    cur.execute("PRAGMA table_info(individuals)")
    have = {r[1] for r in cur.fetchall()}
    if "longevity_years" not in have:
        print("Adding column individuals.longevity_years REAL ...")
        cur.execute("ALTER TABLE individuals ADD COLUMN longevity_years REAL")
        conn.commit()
    else:
        print("Column individuals.longevity_years already present; will overwrite.")

    print("Writing values back (single transaction)...")
    payload = df.select(["longevity_years", "wikidata_id"]).iter_rows()
    BATCH = 50_000
    total = df.height
    cur.execute("BEGIN")
    batch: list[tuple[float, str]] = []
    with tqdm(total=total, unit="row") as bar:
        for row in payload:
            batch.append(row)
            if len(batch) >= BATCH:
                cur.executemany(
                    "UPDATE individuals SET longevity_years = ? WHERE wikidata_id = ?",
                    batch,
                )
                bar.update(len(batch))
                batch.clear()
        if batch:
            cur.executemany(
                "UPDATE individuals SET longevity_years = ? WHERE wikidata_id = ?",
                batch,
            )
            bar.update(len(batch))
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM individuals WHERE longevity_years IS NOT NULL")
    n = cur.fetchone()[0]
    print(f"individuals.longevity_years populated for {n:,} rows.")
    conn.close()
    print(f"Done in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
