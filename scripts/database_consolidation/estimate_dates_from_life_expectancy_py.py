"""Python+DuckDB+Polars port of scripts/database_integration_scripts_V2/
21_estimate_dates_from_life_expectancy. Outputs a CSV instead of writing
back into SQLite, and times the run.

Cascade: (CV-category × 20y period bin) → CV-category → 20y period bin → global,
trained on individuals with both dates at year-or-finer precision (>= 9)
and longevity in [0, 130].
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import duckdb
import polars as pl

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO / "data" / "humans_clean.duckdb"
CV_PATH = (
    REPO
    / "data"
    / "similar_databases"
    / "cross-verified-database"
    / "cross-verified-database.utf8.csv.gz"
)
OUT_DIR = REPO / "temp_files"

BIN_WIDTH = 20
MIN_PRECISION = 9
MIN_BIN_SAMPLES = 5


def parse_year_frac(col: str) -> pl.Expr:
    """Mirror of the Rust parse_year_frac: returns fractional year, BCE negative."""
    s = pl.col(col).cast(pl.Utf8, strict=False)
    is_blank = s.is_null() | (s.str.len_chars() == 0) | s.str.starts_with("_:")
    sign = pl.when(s.str.starts_with("-")).then(-1.0).otherwise(1.0)
    body = pl.when(s.str.starts_with("-")).then(s.str.slice(1)).otherwise(s)
    g = body.str.extract_groups(r"^(?P<y>\d+)(?:-(?P<m>\d+))?(?:-(?P<d>\d+))?")
    y = g.struct.field("y").cast(pl.Float64, strict=False)
    m = g.struct.field("m").cast(pl.Float64, strict=False).fill_null(1.0).clip(1, 12)
    d = g.struct.field("d").cast(pl.Float64, strict=False).fill_null(1.0).clip(1, 31)
    yf = sign * (y + (30.0 * (m - 1.0) + (d - 1.0)) / 365.0)
    return pl.when(is_blank | y.is_null()).then(None).otherwise(yf)


def period_bin(expr: pl.Expr) -> pl.Expr:
    """Floor to BIN_WIDTH, correctly for negatives (year_frac → integer bin)."""
    y = expr.floor().cast(pl.Int64)
    return y - ((y % BIN_WIDTH + BIN_WIDTH) % BIN_WIDTH)


def fmt_iso_year(expr: pl.Expr) -> pl.Expr:
    """Year integer → 'YYYY-01-01' or '-YYYY-01-01' for BCE."""
    abs_y = expr.abs().cast(pl.Int64).cast(pl.Utf8).str.zfill(4)
    return pl.when(expr < 0).then("-" + abs_y + "-01-01").otherwise(abs_y + "-01-01")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--db",
        default=str(DEFAULT_DB),
        help="DuckDB file (full mirror of humans_clean)",
    )
    ap.add_argument(
        "--out", default=str(OUT_DIR / "estimated_dates_from_life_expectancy.csv")
    )
    args = ap.parse_args()

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    timings = {}
    t_total = time.perf_counter()

    print(f"db: {args.db}")
    print(f"cv: {CV_PATH}")
    print(f"out: {args.out}\n")

    # --- Load CV (id, category) ---
    t = time.perf_counter()
    con = duckdb.connect(args.db, read_only=True)
    cv = con.execute(f"""
        SELECT trim(wikidata_code) AS wikidata_id,
               trim(level1_main_occ) AS cat
        FROM read_csv_auto('{CV_PATH}', compression='gzip')
        WHERE wikidata_code IS NOT NULL AND trim(wikidata_code) <> ''
          AND level1_main_occ IS NOT NULL AND trim(level1_main_occ) NOT IN ('', 'Missing')
    """).pl()
    timings["cv_load"] = time.perf_counter() - t
    print(f"  CV (id, category) entries: {cv.height:,}  [{timings['cv_load']:.2f}s]")

    # --- Load individuals (only the columns we need) ---
    t = time.perf_counter()
    ind = con.execute("""
        SELECT wikidata_id, birthdate, deathdate,
               birthdate_precision, deathdate_precision
        FROM individuals
    """).pl()
    con.close()
    timings["ind_load"] = time.perf_counter() - t
    print(f"  individuals loaded:        {ind.height:,}  [{timings['ind_load']:.2f}s]")

    # --- Parse + filter to year-precision anchors ---
    t = time.perf_counter()
    ind = ind.with_columns(
        pl.when(pl.col("birthdate_precision") >= MIN_PRECISION)
        .then(parse_year_frac("birthdate"))
        .otherwise(None)
        .alias("by"),
        pl.when(pl.col("deathdate_precision") >= MIN_PRECISION)
        .then(parse_year_frac("deathdate"))
        .otherwise(None)
        .alias("dy"),
    ).join(cv, on="wikidata_id", how="left")

    have_b = pl.col("by").is_not_null()
    have_d = pl.col("dy").is_not_null()

    both = (
        ind.filter(have_b & have_d)
        .with_columns(
            (pl.col("dy") - pl.col("by")).alias("longevity"),
            period_bin(pl.col("by")).alias("bin_birth"),
            period_bin(pl.col("dy")).alias("bin_death"),
        )
        .filter((pl.col("longevity") >= 0) & (pl.col("longevity") <= 130))
    )
    only_b = ind.filter(have_b & ~have_d).with_columns(
        period_bin(pl.col("by")).alias("bin")
    )
    only_d = ind.filter(~have_b & have_d).with_columns(
        period_bin(pl.col("dy")).alias("bin")
    )
    n_neither = ind.filter(~have_b & ~have_d).height
    timings["parse_classify"] = time.perf_counter() - t
    print(
        f"  classified: both={both.height:,} only_birth={only_b.height:,} "
        f"only_death={only_d.height:,} neither={n_neither:,}  "
        f"[{timings['parse_classify']:.2f}s]"
    )

    # --- Build cascade tables (birth-anchored and death-anchored) ---
    t = time.perf_counter()

    def build_cascade(anchor: str):
        bin_col = "bin_birth" if anchor == "birth" else "bin_death"
        cat_period = (
            both.filter(pl.col("cat").is_not_null())
            .group_by(["cat", bin_col])
            .agg(pl.col("longevity").median().alias("med_cp"), pl.len().alias("n_cp"))
            .filter(pl.col("n_cp") >= MIN_BIN_SAMPLES)
            .rename({bin_col: "bin"})
            .select(["cat", "bin", "med_cp"])
        )
        cat_only = (
            both.filter(pl.col("cat").is_not_null())
            .group_by("cat")
            .agg(pl.col("longevity").median().alias("med_c"))
        )
        period_only = (
            both.group_by(bin_col)
            .agg(pl.col("longevity").median().alias("med_p"), pl.len().alias("n_p"))
            .filter(pl.col("n_p") >= MIN_BIN_SAMPLES)
            .rename({bin_col: "bin"})
            .select(["bin", "med_p"])
        )
        global_med = float(both["longevity"].median())
        return cat_period, cat_only, period_only, global_med

    casc_birth = build_cascade("birth")
    casc_death = build_cascade("death")
    timings["build_cascades"] = time.perf_counter() - t
    print(
        f"  cascades built. global median: birth-anchored={casc_birth[3]:.2f}, "
        f"death-anchored={casc_death[3]:.2f}  [{timings['build_cascades']:.2f}s]"
    )

    # --- Resolve targets via cascading LEFT JOINs ---
    t = time.perf_counter()

    def resolve(
        targets: pl.DataFrame, cascade, anchor_col: str, sign: int
    ) -> pl.DataFrame:
        cat_period, cat_only, period_only, global_med = cascade
        out = (
            targets.join(cat_period, on=["cat", "bin"], how="left")
            .join(cat_only, on="cat", how="left")
            .join(period_only, on="bin", how="left")
            .with_columns(
                pl.coalesce(["med_cp", "med_c", "med_p", pl.lit(global_med)]).alias(
                    "le"
                ),
                pl.when(pl.col("med_cp").is_not_null())
                .then(pl.lit("category+period"))
                .when(pl.col("med_c").is_not_null())
                .then(pl.lit("category"))
                .when(pl.col("med_p").is_not_null())
                .then(pl.lit("period"))
                .otherwise(pl.lit("global"))
                .alias("source"),
            )
            .with_columns(
                (pl.col(anchor_col) + sign * pl.col("le"))
                .floor()
                .cast(pl.Int64)
                .alias("est_year"),
            )
        )
        return out

    est_death = (
        resolve(only_b, casc_birth, "by", +1)
        .with_columns(
            fmt_iso_year(pl.col("est_year")).alias(
                "estimated_deathdate_from_life_expectancy"
            ),
            pl.lit(None, dtype=pl.Utf8).alias(
                "estimated_birthdate_from_life_expectancy"
            ),
        )
        .select(
            [
                "wikidata_id",
                "estimated_birthdate_from_life_expectancy",
                "estimated_deathdate_from_life_expectancy",
                "source",
            ]
        )
    )

    est_birth = (
        resolve(only_d, casc_death, "dy", -1)
        .with_columns(
            fmt_iso_year(pl.col("est_year")).alias(
                "estimated_birthdate_from_life_expectancy"
            ),
            pl.lit(None, dtype=pl.Utf8).alias(
                "estimated_deathdate_from_life_expectancy"
            ),
        )
        .select(
            [
                "wikidata_id",
                "estimated_birthdate_from_life_expectancy",
                "estimated_deathdate_from_life_expectancy",
                "source",
            ]
        )
    )

    estimates = pl.concat([est_death, est_birth], how="vertical")
    timings["resolve"] = time.perf_counter() - t
    print(f"  estimates produced: {estimates.height:,}  [{timings['resolve']:.2f}s]")

    src_counts = (
        estimates.group_by("source").agg(pl.len().alias("n")).sort("n", descending=True)
    )
    for r in src_counts.iter_rows():
        print(f"    source={r[0]}  n={r[1]:,}")

    # --- Write CSV ---
    t = time.perf_counter()
    estimates.write_csv(args.out)
    timings["write_csv"] = time.perf_counter() - t

    timings["total"] = time.perf_counter() - t_total
    print()
    for k, v in timings.items():
        print(f"  {k:18s} {v:7.2f}s")
    print(
        f"\nDONE rows={estimates.height:,} -> {args.out} "
        f"({Path(args.out).stat().st_size/1e6:.1f} MB) "
        f"in {timings['total']:.2f}s"
    )


if __name__ == "__main__":
    main()
