"""V2 of the life-expectancy-based date estimator.

For every individual missing a year-precision `birthdate` OR
`deathdate` (but having the other one at year precision), estimate the
missing date using a cascading lookup:

  1. (CV `level1_main_occ` category, 50-year birth bin)
  2. 50-year birth bin (no category)

The lookup tables themselves come from
`data/life_expectancy_medians_50yr.csv`, which is produced by
`notebooks/25_longevity_evolution.ipynb`. Using the notebook as the
single source of truth guarantees the estimator's medians match what
the graph plots.

For death-anchored estimates we iterate against the birth-bin lookup
(start with `birth = death - 70`, find its bin, refine — converges in
1-2 passes). This keeps every reported median consistent with the
graph (instead of using a death-bin lookup, which would silently bias
toward shorter lives because anyone outliving the bin's right edge
appears in a later bin).

Past-mistake rules (encoded after reviewing
`/Users/charlesdedampierre/Downloads/estimated_dates_annotations.json`):

- A real `birthdate`/`deathdate` is only treated as known if its
  precision is >= 9 (year). Lower-precision values (century / decade /
  millennium) are placeholders like `1901-01-01` for "20th century" and
  must NOT be used as anchor years.
- No estimate is produced if the birth year (real anchor for death
  estimates, estimated value for birth estimates) would be > 1950 —
  the person may still be alive, and the training-set medians beyond
  that period are distorted by survivorship.
- A death estimate is also dropped if it would land within the last 5
  years (`est_year > current_year - 5`) — Wikidata would have the real
  date by then.
- Birth/death estimates are dropped if they violate basic ordering
  (est_birth >= death_year, or est_death <= birth_year).

Output: a CSV with one row per individual we estimate, including all
context the annotator needs to validate it. Use `--sample N` for a
stratified review sample.

Usage:
    python scripts/_one_off/estimate_dates_v2.py \\
        --out data/estimated_dates_v2.csv

    python scripts/_one_off/estimate_dates_v2.py \\
        --sample 200 --out data/estimated_dates_v2_sample.csv
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "humans_clean.sqlite3"
CV_PATH = ROOT / "data" / "similar_databases" / "cross-verified-database" / "cross-verified-database.utf8.csv.gz"
# Single source of truth for the medians: produced by
# `notebooks/25_longevity_evolution.ipynb`. Schema: category, birth_bin,
# median_life_expectancy, mean_life_expectancy, n.
LOOKUP_CSV = ROOT / "data" / "life_expectancy_medians_50yr.csv"

BIN_WIDTH = 50
MIN_PRECISION = 9            # Wikidata: 9=year, 10=month, 11=day
# Don't estimate ANY date for an individual whose birth year — real
# (anchor) or estimated — would be after this cutoff. People born after
# 1950 may still be alive, and the per-period medians beyond that are
# distorted by survivorship.
MAX_BIRTH_YEAR_FOR_ESTIMATE = 1950
DEATH_RECENCY_BUFFER = 5     # don't estimate a death within last 5 yr (Wikidata would have it)
CURRENT_YEAR = dt.date.today().year

PRECISION_LABEL = {
    11: "day", 10: "month", 9: "year",
    8: "decade", 7: "century", 6: "millennium",
}


def parse_year_frac(date_col: str) -> pl.Expr:
    """Wikidata ISO date -> fractional year. Handles '-YYYY-MM-DD' (BC)."""
    s = pl.col(date_col)
    is_bc = s.str.starts_with("-")
    year = s.str.extract(r"^-?(\d{1,5})", 1).cast(pl.Int64, strict=False)
    month = s.str.extract(r"^-?\d{1,5}-(\d{1,2})", 1).cast(pl.Int64, strict=False).fill_null(1)
    day = s.str.extract(r"^-?\d{1,5}-\d{1,2}-(\d{1,2})", 1).cast(pl.Int64, strict=False).fill_null(1)
    signed_year = pl.when(is_bc).then(-year).otherwise(year)
    return (signed_year + (30 * (month - 1) + (day - 1)) / 365.0).alias(f"{date_col}_yr")


def fmt_iso_year(year_int: int | None) -> str | None:
    if year_int is None:
        return None
    if year_int < 0:
        return f"-{abs(year_int):04d}-01-01"
    return f"{year_int:04d}-01-01"


def load_individuals() -> pl.DataFrame:
    print("Loading individuals from SQLite...")
    conn = sqlite3.connect(DB_PATH)
    conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
    cur = conn.cursor()
    cur.execute("""
        SELECT wikidata_id, name_en, description_en, occupations_en,
               country_of_citizenship_en, gender,
               birthdate, birthdate_precision,
               deathdate, deathdate_precision,
               cross_verified_db, wikimedia_links_count,
               estimated_birthdate_from_life_expectancy,
               estimated_deathdate_from_life_expectancy
        FROM individuals
    """)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    conn.close()
    df = pl.DataFrame(rows, schema=cols, orient="row")
    print(f"  {df.height:,} individuals")
    return df


def load_cv() -> pl.DataFrame:
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
    return cv


def load_lookups() -> dict:
    """Load the birth-bin medians produced by
    `notebooks/25_longevity_evolution.ipynb`. The CSV has rows for the
    overall (`category=""`) and per-CV-category (`category=Culture`,
    `Discovery/Science`, ...) bins.
    """
    if not LOOKUP_CSV.exists():
        raise SystemExit(
            f"Lookup CSV not found: {LOOKUP_CSV}\n"
            "Run `notebooks/25_longevity_evolution.ipynb` first to produce it."
        )
    print(f"Loading lookups from {LOOKUP_CSV.name}...")
    df = pl.read_csv(
        LOOKUP_CSV,
        schema_overrides={
            "category": pl.Utf8,
            "birth_bin": pl.Int64,
            "median_life_expectancy": pl.Float64,
        },
    )
    cat_rows = df.filter(pl.col("category") != "")
    overall_rows = df.filter(pl.col("category") == "")
    lookups = {
        "cat_birth_bin": {
            (r["category"], r["birth_bin"]): r["median_life_expectancy"]
            for r in cat_rows.iter_rows(named=True)
        },
        "period_birth_bin": {
            r["birth_bin"]: r["median_life_expectancy"]
            for r in overall_rows.iter_rows(named=True)
        },
    }
    print(f"  cat+birth_bin entries:  {len(lookups['cat_birth_bin']):,}")
    print(f"  birth_bin-only entries: {len(lookups['period_birth_bin']):,}")
    return lookups


def lookup_birth_bin(cat: str | None, birth_bin: int, lookups: dict) -> tuple[float | None, str | None]:
    """Cascade: (cv_category, birth_bin) -> birth_bin -> None."""
    if cat is not None and (cat, birth_bin) in lookups["cat_birth_bin"]:
        return lookups["cat_birth_bin"][(cat, birth_bin)], f"category+birth_bin:{cat}"
    if birth_bin in lookups["period_birth_bin"]:
        return lookups["period_birth_bin"][birth_bin], "birth_bin"
    return None, None


def iterate_birth_from_death(death_year: int, cat: str | None, lookups: dict,
                              max_iter: int = 6) -> tuple[int | None, float | None, str | None, int | None]:
    """Find a self-consistent (birth_year, life_expectancy) pair when
    only the death year is known. The lookup is keyed on birth bin, so
    we iterate until the implied birth bin matches the looked-up median.

    Returns: (est_birth_year, life_exp_used, source, birth_bin) or
             (None, None, None, None) if no lookup ever resolves.
    """
    est_birth = death_year - 70  # initial guess: typical adult life
    seen_bins: set[int] = set()
    for _ in range(max_iter):
        birth_bin = (est_birth // BIN_WIDTH) * BIN_WIDTH
        med, src = lookup_birth_bin(cat, birth_bin, lookups)
        if med is None:
            return None, None, None, None
        new_est = death_year - med
        new_bin = (new_est // BIN_WIDTH) * BIN_WIDTH
        # Converged when the bin no longer changes
        if new_bin == birth_bin:
            return int(round(new_est)), float(med), src, int(birth_bin)
        # Two-cycle (oscillating between adjacent bins): pick the one
        # whose med yields an est in its own bin, or settle on the
        # current.
        if new_bin in seen_bins:
            return int(round(new_est)), float(med), src, int(birth_bin)
        seen_bins.add(birth_bin)
        est_birth = new_est
    # Out of iterations — return the last result anyway
    return int(round(est_birth)), float(med), src, int(birth_bin)


def compute_estimates(df: pl.DataFrame) -> pl.DataFrame:
    """Apply the cascade and skip rules. Returns one row per estimate."""
    cv = load_cv()
    df = df.join(cv, on="wikidata_id", how="left")

    # Drop blank-node Wikidata placeholders from raw date strings
    is_blank = lambda c: pl.col(c).str.starts_with("_:").fill_null(False)
    df = df.with_columns(
        [
            pl.when(pl.col("birthdate").is_null() | is_blank("birthdate"))
            .then(None).otherwise(pl.col("birthdate")).alias("birthdate"),
            pl.when(pl.col("deathdate").is_null() | is_blank("deathdate"))
            .then(None).otherwise(pl.col("deathdate")).alias("deathdate"),
        ]
    ).with_columns([parse_year_frac("birthdate"), parse_year_frac("deathdate")])

    # Year-precision masks: only treat a date as known if precision >= 9
    df = df.with_columns(
        [
            pl.when(pl.col("birthdate_precision") >= MIN_PRECISION)
            .then(pl.col("birthdate_yr")).otherwise(None).alias("birth_yr_known"),
            pl.when(pl.col("deathdate_precision") >= MIN_PRECISION)
            .then(pl.col("deathdate_yr")).otherwise(None).alias("death_yr_known"),
        ]
    )

    lookups = load_lookups()

    # Targets: missing exactly one year-precision date
    has_b = pl.col("birth_yr_known").is_not_null()
    has_d = pl.col("death_yr_known").is_not_null()
    targets = df.filter((has_b ^ has_d))  # XOR: exactly one known
    print(f"Targets (exactly one year-precision date): {targets.height:,}")

    rows_out: list[dict] = []
    skip_reasons: dict[str, int] = {}

    def _bump(reason: str) -> None:
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

    for r in targets.iter_rows(named=True):
        b_yr = r["birth_yr_known"]
        d_yr = r["death_yr_known"]
        cat = r["level1_main_occ"]

        if b_yr is not None:
            anchor_kind = "birth"
            anchor_yr = b_yr
            est_kind = "death"
        else:
            anchor_kind = "death"
            anchor_yr = d_yr
            est_kind = "birth"

        anchor_int = int(anchor_yr)

        # Resolve life-expectancy median + report which birth-bin it came from
        if est_kind == "death":
            # Anchor IS the birth — use its own bin for the lookup
            birth_bin = (anchor_int // BIN_WIDTH) * BIN_WIDTH
            med, source = lookup_birth_bin(cat, birth_bin, lookups)
            if med is None:
                _bump("no_lookup_for_birth_bin")
                continue
            est_year = int(round(anchor_int + med))
            # Skip rule: birth too recent — person may still be alive.
            if anchor_int >= MAX_BIRTH_YEAR_FOR_ESTIMATE:
                _bump(f"birth_ge_{MAX_BIRTH_YEAR_FOR_ESTIMATE}_skip")
                continue
            if est_year > CURRENT_YEAR - DEATH_RECENCY_BUFFER:
                _bump("est_death_too_recent")
                continue
        else:
            # Anchor is the DEATH — iterate against birth-bin lookup
            iter_birth, med, source, birth_bin = iterate_birth_from_death(anchor_int, cat, lookups)
            if iter_birth is None:
                _bump("no_lookup_for_iterated_birth_bin")
                continue
            est_year = iter_birth
            # Same cutoff applied via the *estimated* birth year
            if est_year >= MAX_BIRTH_YEAR_FOR_ESTIMATE:
                _bump(f"est_birth_ge_{MAX_BIRTH_YEAR_FOR_ESTIMATE}_skip")
                continue
            if est_year > CURRENT_YEAR:
                _bump("est_birth_in_future")
                continue

        period = birth_bin

        rows_out.append({
            "wikidata_id": r["wikidata_id"],
            "name_en": (r["name_en"] or "")[:200],
            "description_en": (r["description_en"] or "")[:300],
            "occupations_en": (r["occupations_en"] or "")[:300],
            "country_of_citizenship_en": (r["country_of_citizenship_en"] or "")[:200],
            "gender": r["gender"] or "",
            "real_birth": r["birthdate"],
            "real_birth_precision": int(r["birthdate_precision"]) if r["birthdate_precision"] is not None else None,
            "real_birth_precision_label": PRECISION_LABEL.get(int(r["birthdate_precision"]), "") if r["birthdate_precision"] is not None else "",
            "real_death": r["deathdate"],
            "real_death_precision": int(r["deathdate_precision"]) if r["deathdate_precision"] is not None else None,
            "real_death_precision_label": PRECISION_LABEL.get(int(r["deathdate_precision"]), "") if r["deathdate_precision"] is not None else "",
            "cv_category": cat or "",
            "in_cv": int(r["cross_verified_db"] or 0),
            "wikimedia_links_count": int(r["wikimedia_links_count"] or 0),
            "anchor_kind": anchor_kind,
            "anchor_year": anchor_int,
            "period_bin": period,
            "est_kind": est_kind,
            "est_year": est_year,
            "est_date": fmt_iso_year(est_year),
            "median_life_expectancy_used": round(float(med), 2),
            "lookup_source": source,
            "implied_lifespan": int(round(abs(est_year - anchor_int))),
            "old_est_birth": r["estimated_birthdate_from_life_expectancy"],
            "old_est_death": r["estimated_deathdate_from_life_expectancy"],
        })

    print(f"Estimates produced: {len(rows_out):,}")
    print("Skipped (with reasons):")
    for k, v in sorted(skip_reasons.items(), key=lambda x: -x[1]):
        print(f"  {k:32s} {v:>10,}")

    out = pl.DataFrame(rows_out)
    return out


def stratified_sample(df: pl.DataFrame, n: int, seed: int = 42) -> pl.DataFrame:
    """Sample roughly evenly across (cv_category × est_kind). Categories
    with no rows are skipped; remaining slots are filled from the largest
    surviving stratum."""
    cats = (df["cv_category"].fill_null("").unique()).to_list()
    strata = [(c, k) for c in cats for k in ("birth", "death")]
    per = max(1, n // max(1, len(strata)))

    parts: list[pl.DataFrame] = []
    for c, k in strata:
        sub = df.filter((pl.col("cv_category") == c) & (pl.col("est_kind") == k))
        if sub.height == 0:
            continue
        parts.append(sub.sample(n=min(per, sub.height), seed=seed))

    sampled = pl.concat(parts) if parts else df.head(0)
    if sampled.height < n:
        rest = df.join(sampled.select("wikidata_id"), on="wikidata_id", how="anti")
        if rest.height > 0:
            extra = rest.sample(n=min(n - sampled.height, rest.height), seed=seed)
            sampled = pl.concat([sampled, extra])
    return sampled.sample(fraction=1.0, seed=seed)  # shuffle


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True, help="output CSV path")
    p.add_argument("--sample", type=int, default=0, help="if > 0, write a stratified sample of N rows instead of the full set")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    df_ind = load_individuals()
    estimates = compute_estimates(df_ind)
    if estimates.height == 0:
        print("No estimates produced — nothing to write.")
        return

    if args.sample and args.sample > 0:
        out = stratified_sample(estimates, args.sample, seed=args.seed)
        print(f"Sampled {out.height} rows for review")
    else:
        out = estimates

    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.write_csv(args.out)
    print(f"Wrote {out.height:,} rows -> {args.out}")


if __name__ == "__main__":
    main()
