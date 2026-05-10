"""Estimate missing birthdate or deathdate from a life-expectancy cascade.

Training set: individuals with BOTH dates at year-or-finer precision (>= 9)
and longevity in [0, 130]. From them we compute median longevity per
(category × 20y period bin), per category, per period, and globally.

Targets:    individuals with EXACTLY ONE of (birthdate, deathdate) at year
or decade precision (>= 8). For each target we look up the median in the
most specific available level (cascade order below) and add/subtract it
from the known anchor to impute the missing year.

Cascade (most specific first):
    1. category + period
    2. category
    3. period
    4. global

Output: temp_files/estimated_dates_from_life_expectancy.csv with columns
    wikidata_id,
    estimated_birthdate_from_life_expectancy,
    estimated_deathdate_from_life_expectancy,
    source
"""

from pathlib import Path
import time

import duckdb
import polars as pl

REPO     = Path(__file__).resolve().parents[2]
DB_PATH  = REPO / "data" / "humans_clean.duckdb"
CV_PATH  = REPO / "data" / "similar_databases" / "cross-verified-database" / "cross-verified-database.utf8.csv.gz"
OUT_PATH = REPO / "temp_files" / "estimated_dates_from_life_expectancy.csv"

PERIOD_BIN_WIDTH = 20
PRECISION_YEAR   = 9
PRECISION_DECADE = 8
MIN_LONGEVITY    = 0
MAX_LONGEVITY    = 130
MIN_BIN_SAMPLES  = 5


def parse_iso_year_fraction(date_column: str) -> pl.Expr:
    raw      = pl.col(date_column).cast(pl.Utf8, strict=False)
    is_blank = raw.is_null() | (raw.str.len_chars() == 0) | raw.str.starts_with("_:")
    sign     = pl.when(raw.str.starts_with("-")).then(-1.0).otherwise(1.0)
    body     = pl.when(raw.str.starts_with("-")).then(raw.str.slice(1)).otherwise(raw)
    parts    = body.str.extract_groups(r"^(?P<y>\d+)(?:-(?P<m>\d+))?(?:-(?P<d>\d+))?")
    year     = parts.struct.field("y").cast(pl.Float64, strict=False)
    month    = parts.struct.field("m").cast(pl.Float64, strict=False).fill_null(1.0).clip(1, 12)
    day      = parts.struct.field("d").cast(pl.Float64, strict=False).fill_null(1.0).clip(1, 31)
    fractional = sign * (year + (30.0 * (month - 1.0) + (day - 1.0)) / 365.0)
    return pl.when(is_blank | year.is_null()).then(None).otherwise(fractional)


def floor_to_period(year_expr: pl.Expr) -> pl.Expr:
    y = year_expr.floor().cast(pl.Int64)
    return y - ((y % PERIOD_BIN_WIDTH + PERIOD_BIN_WIDTH) % PERIOD_BIN_WIDTH)


def year_to_iso(year_expr: pl.Expr) -> pl.Expr:
    abs_year = year_expr.abs().cast(pl.Int64).cast(pl.Utf8).str.zfill(4)
    return pl.when(year_expr < 0).then("-" + abs_year + "-01-01").otherwise(abs_year + "-01-01")


def load_individuals(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    df = con.execute("""
        SELECT wikidata_id, birthdate, deathdate,
               birthdate_precision, deathdate_precision
        FROM   individuals
    """).pl()
    return df.with_columns(
        pl.when(pl.col("birthdate_precision") >= PRECISION_DECADE)
          .then(parse_iso_year_fraction("birthdate"))
          .otherwise(None)
          .alias("birth_year_frac"),
        pl.when(pl.col("deathdate_precision") >= PRECISION_DECADE)
          .then(parse_iso_year_fraction("deathdate"))
          .otherwise(None)
          .alias("death_year_frac"),
    )


def load_cv_categories() -> pl.DataFrame:
    return (
        pl.read_csv(
            CV_PATH,
            columns=['wikidata_code', 'level1_main_occ'],
            schema_overrides={'wikidata_code': pl.Utf8, 'level1_main_occ': pl.Utf8},
        )
        .drop_nulls(['wikidata_code', 'level1_main_occ'])
        .filter(~pl.col('level1_main_occ').is_in(['', 'Missing']))
        .rename({'wikidata_code': 'wikidata_id', 'level1_main_occ': 'category'})
    )


def build_cascade(training: pl.DataFrame, period_col: str) -> dict:
    by_cat_period = (
        training.filter(pl.col("category").is_not_null())
                .group_by(["category", period_col])
                .agg(
                    pl.col("longevity").median().alias("median_longevity"),
                    pl.len().alias("n"),
                )
                .filter(pl.col("n") >= MIN_BIN_SAMPLES)
                .rename({period_col: "period"})
                .select(["category", "period", "median_longevity"])
    )
    by_cat = (
        training.filter(pl.col("category").is_not_null())
                .group_by("category")
                .agg(pl.col("longevity").median().alias("median_longevity"))
    )
    by_period = (
        training.group_by(period_col)
                .agg(
                    pl.col("longevity").median().alias("median_longevity"),
                    pl.len().alias("n"),
                )
                .filter(pl.col("n") >= MIN_BIN_SAMPLES)
                .rename({period_col: "period"})
                .select(["period", "median_longevity"])
    )
    return {
        "category_period": by_cat_period,
        "category":        by_cat,
        "period":          by_period,
        "global":          float(training["longevity"].median()),
    }


def apply_cascade(targets: pl.DataFrame, cascade: dict, anchor_col: str, sign: int) -> pl.DataFrame:
    return (
        targets
        .join(cascade["category_period"].rename({"median_longevity": "med_cp"}),
              on=["category", "period"], how="left")
        .join(cascade["category"].rename({"median_longevity": "med_c"}),
              on="category", how="left")
        .join(cascade["period"].rename({"median_longevity": "med_p"}),
              on="period", how="left")
        .with_columns(
            pl.coalesce(["med_cp", "med_c", "med_p", pl.lit(cascade["global"])]).alias("median_used"),
            pl.when(pl.col("med_cp").is_not_null()).then(pl.lit("category+period"))
              .when(pl.col("med_c").is_not_null()).then(pl.lit("category"))
              .when(pl.col("med_p").is_not_null()).then(pl.lit("period"))
              .otherwise(pl.lit("global"))
              .alias("source"),
        )
        .with_columns(
            (pl.col(anchor_col) + sign * pl.col("median_used")).floor().cast(pl.Int64).alias("est_year"),
        )
    )


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"db:  {DB_PATH}")
    print(f"cv:  {CV_PATH}")
    print(f"out: {OUT_PATH}")
    t0 = time.perf_counter()

    con = duckdb.connect(str(DB_PATH), read_only=True)
    individuals = load_individuals(con)
    con.close()
    categories  = load_cv_categories()
    print(f"  individuals loaded:           {individuals.height:,}")
    print(f"  CV categories loaded:         {categories.height:,}")

    individuals = individuals.join(categories, on="wikidata_id", how="left")

    has_birth_anchor = pl.col("birth_year_frac").is_not_null()
    has_death_anchor = pl.col("death_year_frac").is_not_null()
    birth_year_precise = pl.col("birthdate_precision") >= PRECISION_YEAR
    death_year_precise = pl.col("deathdate_precision") >= PRECISION_YEAR

    training = (
        individuals
        .filter(has_birth_anchor & has_death_anchor & birth_year_precise & death_year_precise)
        .with_columns(
            (pl.col("death_year_frac") - pl.col("birth_year_frac")).alias("longevity"),
            floor_to_period(pl.col("birth_year_frac")).alias("birth_period"),
            floor_to_period(pl.col("death_year_frac")).alias("death_period"),
        )
        .filter((pl.col("longevity") >= MIN_LONGEVITY) & (pl.col("longevity") <= MAX_LONGEVITY))
    )
    only_birth = (
        individuals
        .filter(has_birth_anchor & ~has_death_anchor)
        .with_columns(floor_to_period(pl.col("birth_year_frac")).alias("period"))
    )
    only_death = (
        individuals
        .filter(~has_birth_anchor & has_death_anchor)
        .with_columns(floor_to_period(pl.col("death_year_frac")).alias("period"))
    )
    n_neither = individuals.filter(~has_birth_anchor & ~has_death_anchor).height
    print(f"  training (both year-precise): {training.height:,}")
    print(f"  only_birth → estimate death:  {only_birth.height:,}")
    print(f"  only_death → estimate birth:  {only_death.height:,}")
    print(f"  neither:                      {n_neither:,}")

    cascade_from_birth = build_cascade(training, "birth_period")
    cascade_from_death = build_cascade(training, "death_period")
    print(f"  global longevity median (birth-anchored): {cascade_from_birth['global']:.2f}")
    print(f"  global longevity median (death-anchored): {cascade_from_death['global']:.2f}")

    estimated_death = apply_cascade(only_birth, cascade_from_birth, "birth_year_frac", +1).select(
        pl.col("wikidata_id"),
        pl.lit(None, dtype=pl.Utf8).alias("estimated_birthdate_from_life_expectancy"),
        year_to_iso(pl.col("est_year")).alias("estimated_deathdate_from_life_expectancy"),
        pl.col("source"),
    )
    estimated_birth = apply_cascade(only_death, cascade_from_death, "death_year_frac", -1).select(
        pl.col("wikidata_id"),
        year_to_iso(pl.col("est_year")).alias("estimated_birthdate_from_life_expectancy"),
        pl.lit(None, dtype=pl.Utf8).alias("estimated_deathdate_from_life_expectancy"),
        pl.col("source"),
    )
    estimates = pl.concat([estimated_death, estimated_birth], how="vertical")

    print(f"\n  estimates produced: {estimates.height:,}")
    by_source = estimates.group_by("source").agg(pl.len().alias("n")).sort("n", descending=True)
    for row in by_source.iter_rows(named=True):
        print(f"    {row['source']:18s} {row['n']:>10,}")

    estimates.write_csv(OUT_PATH)
    elapsed = time.perf_counter() - t0
    size_mb = OUT_PATH.stat().st_size / 1e6
    print(f"\nDONE rows={estimates.height:,} → {OUT_PATH} ({size_mb:.1f} MB) in {elapsed:.2f}s")


if __name__ == "__main__":
    main()
