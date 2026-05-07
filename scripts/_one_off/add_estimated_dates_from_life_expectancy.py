"""Add estimated_birthdate_from_life_expectancy and
estimated_deathdate_from_life_expectancy columns to `individuals`.

For every individual missing exactly one of (birthdate, deathdate) but
having a parsable other date (year-level precision >= 9), we estimate the
missing date by adding/subtracting a median life expectancy drawn from a
cascading lookup:

  1. (CV occupational category, 20-year period bin)  -- both available
  2. CV occupational category overall                -- if period is empty
  3. 20-year period overall                          -- no CV category
  4. global median                                   -- last resort

The 20-year period is keyed on the date we *have*. For people with only a
deathdate we anchor on the death period; for people with only a birthdate
we anchor on the birth period. Medians come from the ~3.1M individuals
that already have both dates at precision >= 9.

Output dates are written as ISO 'YYYY-01-01' (or '-YYYY-01-01' for BC),
matching the existing `birthdate` / `deathdate` formatting.

Two-phase write: estimates are first saved to a parquet checkpoint
(`data/estimated_dates_from_life_expectancy.parquet`) so they survive a
locked database; the schema change + UPDATEs are then attempted. Re-running
the script after a lock is released will skip the recomputation if the
checkpoint exists.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import polars as pl
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "humans_clean.sqlite3"
CV_PATH = ROOT / "data" / "similar_databases" / "cross-verified-database" / "cross-verified-database.utf8.csv.gz"
CHECKPOINT = ROOT / "data" / "estimated_dates_from_life_expectancy.parquet"

BIN_WIDTH = 20  # 20-year period bins
MIN_PRECISION = 9  # year-level


def parse_year_frac(date_col: str) -> pl.Expr:
    """Wikidata ISO date -> fractional year. Handles '-YYYY-MM-DD' (BC)."""
    s = pl.col(date_col)
    is_bc = s.str.starts_with("-")
    year = s.str.extract(r"^-?(\d{1,5})", 1).cast(pl.Int64, strict=False)
    month = s.str.extract(r"^-?\d{1,5}-(\d{1,2})", 1).cast(pl.Int64, strict=False).fill_null(1)
    day = s.str.extract(r"^-?\d{1,5}-\d{1,2}-(\d{1,2})", 1).cast(pl.Int64, strict=False).fill_null(1)
    signed_year = pl.when(is_bc).then(-year).otherwise(year)
    return (signed_year + (30 * (month - 1) + (day - 1)) / 365.0).alias(f"{date_col}_yr")


def fmt_iso(year_int: int) -> str:
    """Format an integer year (negative => BC) as ISO 'YYYY-01-01'."""
    if year_int < 0:
        return f"-{abs(year_int):04d}-01-01"
    return f"{year_int:04d}-01-01"


def compute_estimates() -> pl.DataFrame:
    """Return a DataFrame with columns:
    wikidata_id, estimated_birthdate, estimated_deathdate, source.
    Only includes rows where exactly one of the two original dates was
    missing AND we could fill it in.
    """
    print("Loading individuals (wikidata_id, dates, precision)...")
    conn = sqlite3.connect(DB_PATH)
    ind = pl.read_database(
        """
        SELECT wikidata_id, birthdate, deathdate,
               birthdate_precision, deathdate_precision
        FROM individuals
        """,
        conn,
    )
    conn.close()
    print(f"  {ind.height:,} total individuals")

    is_blank = lambda c: pl.col(c).str.starts_with("_:")
    ind = ind.with_columns(
        [
            pl.when(pl.col("birthdate").is_null() | is_blank("birthdate"))
            .then(None)
            .otherwise(pl.col("birthdate"))
            .alias("birthdate"),
            pl.when(pl.col("deathdate").is_null() | is_blank("deathdate"))
            .then(None)
            .otherwise(pl.col("deathdate"))
            .alias("deathdate"),
        ]
    ).with_columns([parse_year_frac("birthdate"), parse_year_frac("deathdate")])

    # Mask precisions: only treat dates as usable if precision >= MIN_PRECISION
    ind = ind.with_columns(
        [
            pl.when(pl.col("birthdate_precision") >= MIN_PRECISION)
            .then(pl.col("birthdate_yr"))
            .otherwise(None)
            .alias("birthdate_yr"),
            pl.when(pl.col("deathdate_precision") >= MIN_PRECISION)
            .then(pl.col("deathdate_yr"))
            .otherwise(None)
            .alias("deathdate_yr"),
        ]
    )

    has_b = pl.col("birthdate_yr").is_not_null()
    has_d = pl.col("deathdate_yr").is_not_null()

    n_both = ind.filter(has_b & has_d).height
    n_only_b = ind.filter(has_b & ~has_d).height
    n_only_d = ind.filter(~has_b & has_d).height
    n_neither = ind.filter(~has_b & ~has_d).height
    print(f"  with both dates : {n_both:,}")
    print(f"  with only birth : {n_only_b:,}")
    print(f"  with only death : {n_only_d:,}")
    print(f"  with neither    : {n_neither:,}")

    # ---- CV categories ----
    print("Loading CV level1_main_occ...")
    cv = (
        pl.read_csv(
            CV_PATH,
            columns=["wikidata_code", "level1_main_occ"],
            schema_overrides={"wikidata_code": pl.Utf8, "level1_main_occ": pl.Utf8},
        )
        .drop_nulls(["wikidata_code", "level1_main_occ"])
        .filter(pl.col("level1_main_occ") != "Missing")
        .rename({"wikidata_code": "wikidata_id"})
        .unique(subset=["wikidata_id"])
    )
    print(f"  {cv.height:,} CV (wikidata_id, category) pairs")

    ind = ind.join(cv, on="wikidata_id", how="left")

    # ---- Build training set (both dates valid) ----
    train = ind.filter(has_b & has_d).with_columns(
        [
            (pl.col("deathdate_yr") - pl.col("birthdate_yr")).alias("longevity"),
            (pl.col("birthdate_yr") // BIN_WIDTH * BIN_WIDTH).cast(pl.Int64).alias("bin_birth"),
            (pl.col("deathdate_yr") // BIN_WIDTH * BIN_WIDTH).cast(pl.Int64).alias("bin_death"),
        ]
    ).filter((pl.col("longevity") >= 0) & (pl.col("longevity") <= 130))
    print(f"  training set (longevity in [0,130]): {train.height:,}")

    # We build two parallel period lookups (birth-anchored and death-anchored)
    # because someone with only a deathdate must be matched on the death-bin
    # of the training individuals, and vice versa.

    def _lookup(period_col: str) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, float]:
        cat_period = (
            train.drop_nulls("level1_main_occ")
            .group_by(["level1_main_occ", period_col])
            .agg(pl.col("longevity").median().alias("med"), pl.len().alias("n"))
            .filter(pl.col("n") >= 5)
            .rename({period_col: "period"})
        )
        cat_only = (
            train.drop_nulls("level1_main_occ")
            .group_by("level1_main_occ")
            .agg(pl.col("longevity").median().alias("med"), pl.len().alias("n"))
        )
        period_only = (
            train.group_by(period_col)
            .agg(pl.col("longevity").median().alias("med"), pl.len().alias("n"))
            .filter(pl.col("n") >= 5)
            .rename({period_col: "period"})
        )
        global_med = float(train["longevity"].median())
        return cat_period, cat_only, period_only, global_med

    cp_b, c_b, p_b, glob_b = _lookup("bin_birth")
    cp_d, c_d, p_d, glob_d = _lookup("bin_death")
    print(f"  global median longevity: {glob_b:.2f} (birth-bin) / {glob_d:.2f} (death-bin)")

    def _resolve(targets: pl.DataFrame, period_col: str, cat_period: pl.DataFrame, cat_only: pl.DataFrame, period_only: pl.DataFrame, glob: float) -> pl.DataFrame:
        # cascade joins; at each step "med" may already be filled
        out = (
            targets
            .join(cat_period, left_on=["level1_main_occ", period_col], right_on=["level1_main_occ", "period"], how="left")
            .rename({"med": "med_1"}).drop("n")
            .join(cat_only, on="level1_main_occ", how="left")
            .rename({"med": "med_2"}).drop("n")
            .join(period_only, left_on=period_col, right_on="period", how="left")
            .rename({"med": "med_3"}).drop("n")
            .with_columns(
                pl.coalesce(["med_1", "med_2", "med_3", pl.lit(glob)]).alias("life_expectancy"),
                pl.when(pl.col("med_1").is_not_null()).then(pl.lit("category+period"))
                .when(pl.col("med_2").is_not_null()).then(pl.lit("category"))
                .when(pl.col("med_3").is_not_null()).then(pl.lit("period"))
                .otherwise(pl.lit("global"))
                .alias("source"),
            )
            .drop(["med_1", "med_2", "med_3"])
        )
        return out

    # Targets missing only deathdate (have birth, anchored on birth bin)
    only_b = (
        ind.filter(has_b & ~has_d)
        .with_columns((pl.col("birthdate_yr") // BIN_WIDTH * BIN_WIDTH).cast(pl.Int64).alias("bin_birth"))
    )
    est_d = _resolve(only_b, "bin_birth", cp_b, c_b, p_b, glob_b).with_columns(
        (pl.col("birthdate_yr") + pl.col("life_expectancy")).floor().cast(pl.Int64).alias("est_death_year")
    )

    # Targets missing only birthdate (have death, anchored on death bin)
    only_d = (
        ind.filter(~has_b & has_d)
        .with_columns((pl.col("deathdate_yr") // BIN_WIDTH * BIN_WIDTH).cast(pl.Int64).alias("bin_death"))
    )
    est_b = _resolve(only_d, "bin_death", cp_d, c_d, p_d, glob_d).with_columns(
        (pl.col("deathdate_yr") - pl.col("life_expectancy")).floor().cast(pl.Int64).alias("est_birth_year")
    )

    print(f"  filling deathdate for {est_d.height:,} (have only birth)")
    print(f"  filling birthdate for {est_b.height:,} (have only death)")

    # Format estimates as ISO strings
    def _iso(col: str) -> pl.Expr:
        y = pl.col(col)
        return (
            pl.when(y.is_null())
            .then(None)
            .when(y < 0)
            .then(pl.format("-{}-01-01", (-y).cast(pl.Int64).cast(pl.Utf8).str.zfill(4)))
            .otherwise(pl.format("{}-01-01", y.cast(pl.Int64).cast(pl.Utf8).str.zfill(4)))
        )

    est_d_out = est_d.select(
        pl.col("wikidata_id"),
        pl.lit(None, dtype=pl.Utf8).alias("estimated_birthdate_from_life_expectancy"),
        _iso("est_death_year").alias("estimated_deathdate_from_life_expectancy"),
        pl.col("source").alias("estimate_source"),
        pl.col("life_expectancy").round(2).alias("life_expectancy_used"),
    )
    est_b_out = est_b.select(
        pl.col("wikidata_id"),
        _iso("est_birth_year").alias("estimated_birthdate_from_life_expectancy"),
        pl.lit(None, dtype=pl.Utf8).alias("estimated_deathdate_from_life_expectancy"),
        pl.col("source").alias("estimate_source"),
        pl.col("life_expectancy").round(2).alias("life_expectancy_used"),
    )
    out = pl.concat([est_d_out, est_b_out], how="vertical")
    print(f"  total estimates: {out.height:,}")
    print(out.group_by("estimate_source").len().sort("len", descending=True))
    return out


def write_back(estimates: pl.DataFrame) -> None:
    print("Connecting to SQLite (write)...")
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(individuals)")
    have = {r[1] for r in cur.fetchall()}
    for col in (
        "estimated_birthdate_from_life_expectancy",
        "estimated_deathdate_from_life_expectancy",
    ):
        if col not in have:
            print(f"  ALTER TABLE individuals ADD COLUMN {col} TEXT")
            cur.execute(f"ALTER TABLE individuals ADD COLUMN {col} TEXT")
    conn.commit()

    print("Writing UPDATEs in a single transaction...")
    cur.execute("BEGIN")
    BATCH = 50_000
    rows_b = (
        estimates
        .filter(pl.col("estimated_birthdate_from_life_expectancy").is_not_null())
        .select(["estimated_birthdate_from_life_expectancy", "wikidata_id"])
    )
    rows_d = (
        estimates
        .filter(pl.col("estimated_deathdate_from_life_expectancy").is_not_null())
        .select(["estimated_deathdate_from_life_expectancy", "wikidata_id"])
    )

    for label, rows, sql in [
        ("birthdate", rows_b, "UPDATE individuals SET estimated_birthdate_from_life_expectancy = ? WHERE wikidata_id = ?"),
        ("deathdate", rows_d, "UPDATE individuals SET estimated_deathdate_from_life_expectancy = ? WHERE wikidata_id = ?"),
    ]:
        total = rows.height
        with tqdm(total=total, unit="row", desc=label) as bar:
            buf: list[tuple] = []
            for r in rows.iter_rows():
                buf.append(r)
                if len(buf) >= BATCH:
                    cur.executemany(sql, buf)
                    bar.update(len(buf))
                    buf.clear()
            if buf:
                cur.executemany(sql, buf)
                bar.update(len(buf))
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM individuals WHERE estimated_birthdate_from_life_expectancy IS NOT NULL")
    n_b = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM individuals WHERE estimated_deathdate_from_life_expectancy IS NOT NULL")
    n_d = cur.fetchone()[0]
    print(f"  estimated_birthdate populated: {n_b:,}")
    print(f"  estimated_deathdate populated: {n_d:,}")
    conn.close()


def main() -> None:
    t0 = time.perf_counter()

    if CHECKPOINT.exists():
        print(f"Loading checkpoint: {CHECKPOINT}")
        estimates = pl.read_parquet(CHECKPOINT)
        print(f"  {estimates.height:,} cached estimates")
    else:
        estimates = compute_estimates()
        print(f"Saving checkpoint -> {CHECKPOINT}")
        estimates.write_parquet(CHECKPOINT)

    write_back(estimates)
    print(f"Done in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
