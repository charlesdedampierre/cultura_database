"""01 — Build individuals_floruit_period (DuckDB rewrite, 2026-05).

Reads from `data/humans_clean.duckdb`, derives a floruit period for every
individual using a tiered candidate-selection algorithm, and writes the
results to `temp_files/individuals_floruit_period.csv` for review. Once
validated via `annotations/floruit_period_review/`, a separate insert step
copies the CSV back into the DuckDB.

Selection rules (ordered)
-------------------------
We rank every available date signal and pick the best one. Higher tier =
preferred; ties are broken by source (Wikidata-property > description >
works/CV/Wikipedia).

  Tier A — year-precise signals (precision >= 9)
    A1  floruit_property        Wikidata P1317 with year precision
    A2  floruit_description     "fl 1645" / "active 1633" in description (no
                                birth/death in description)
    A3  floruit_wikipedia       single-year `floruit_from_wikipedia`
    A4  works_span              works_period spans more than one year
    A5  works_single            works_period is a single year (expanded)
    A6  birth_death_property    both birth+death year-precise from Wikidata
    A7  birth_death_description birth+death from description
    A8  birth_death_cv          birth+death from CV database
    A9  birth_death_wikipedia   birth+death from Wikipedia (or floruit span)
    A10 birth_only_*            birth alone (any year-precise source)
    A11 death_only_*            death alone (any year-precise source)

  Tier B — coarse signals (decade or century precision)
    B1  floruit_property_century   Wikidata floruit at century precision
    B2  birth_death_century        birth+death century-precise
    B3  birth_century / death_century

  Tier C — estimated (life-expectancy)
    C1  birth_death_estimated      paired with the known year-precise side
    C2  birth_death_estimated_full both sides estimated

Anchoring
---------
A floruit *date* (single year) anchors a 30..55 productive window.
  - If a birth year is also known we measure age and pick the side
    (start vs end) closest to the date.
  - Otherwise we treat the floruit date as the start (earlier-end-only is
    a less useful default for downstream polity matching).

A birth+death pair gives `start = birth + 30`, `end = min(birth + 55, death)`.

A works span is taken exactly: `start = first_work_year`, `end = last_work_year`.

Century-only signals expand to the full century (or two-century window
when birth+death sit in different centuries).

Under-30 cutoff: people whose best birth year falls after `CURRENT_YEAR - 30`
get no floruit unless an explicit floruit signal is present.

Usage
-----
    python3 01_individuals_floruit_period.py            # 10k sample, dry CSV
    python3 01_individuals_floruit_period.py --full     # full 13M run
    python3 01_individuals_floruit_period.py --sample 50000
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import duckdb
from tqdm import tqdm

# --------------------------------------------------------------------------
# Paths & constants
# --------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DUCKDB_PATH = PROJECT_ROOT / "data" / "humans_clean.duckdb"
CV_PATH = (
    PROJECT_ROOT
    / "data"
    / "similar_databases"
    / "cross-verified-database"
    / "cross-verified-database.utf8.csv.gz"
)
OUTPUT_CSV = PROJECT_ROOT / "temp_files" / "individuals_floruit_period.csv"
TASK_LOG = PROJECT_ROOT / "task.log"

CURRENT_YEAR = 2026

# Productive-age windows per CV level1 occupation (Q1, Q3 of age-at-floruit).
# Computed in notebooks/06_floruits.ipynb against year-precise birth + explicit
# Wikidata floruit (P1317).
PRODUCTIVE_AGE = {
    "global": (29, 55),
    "Culture": (30, 62),
    "Discovery/Science": (33, 62),
    "Leadership": (34, 67),
    "Sports/Games": (21, 35),
}
GLOBAL_LO, GLOBAL_HI = PRODUCTIVE_AGE["global"]
UNDER_FLORUIT_BIRTH_CUTOFF = CURRENT_YEAR - GLOBAL_LO  # 1997


def productive_age(category):
    return PRODUCTIVE_AGE.get(category, PRODUCTIVE_AGE["global"])


# Columns pulled from `individuals`. Keeping the list close to the rules.
QUERY_COLS = [
    "wikidata_id",
    "name_en",
    "description_en",
    "birthdate",
    "birthdate_precision",
    "deathdate",
    "deathdate_precision",
    "floruit_date",
    "floruit_precision",
    "floruit_year",
    "dates_in_description",
    "birthdate_in_description",
    "deathdate_in_description",
    "floruit_year_in_description",
    "birthdate_from_CV",
    "deathdate_from_CV",
    "birthdate_from_wikipedia",
    "deathdate_from_wikipedia",
    "floruit_from_wikipedia",
    "birthdate_from_life_expectancy",
    "deathdate_from_life_expectancy",
    "works_period",
]

OUT_COLS = [
    "wikidata_id",
    "name_en",
    "birth_year",
    "birth_precision",
    "death_year",
    "death_precision",
    "floruit_year_property",
    "floruit_property_precision",
    "floruit_year_in_description",
    "works_period",
    "floruit_period_start",
    "floruit_period_end",
    "floruit_period",
    "method",
    "source",
    "precision_class",
    "estimated",
]


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------


def log(msg: str) -> None:
    print(msg, flush=True)
    try:
        with open(TASK_LOG, "a") as fh:
            fh.write(msg + "\n")
    except OSError:
        pass


# --------------------------------------------------------------------------
# Year / span parsers
# --------------------------------------------------------------------------


def parse_year(s):
    if s is None:
        return None
    if isinstance(s, int):
        return s
    s = str(s).strip()
    if not s or s.startswith("_:"):
        return None
    sign = 1
    if s.startswith("-"):
        sign = -1
        s = s[1:]
    elif s.startswith("+"):
        s = s[1:]
    head = s.split("-", 1)[0].split("T", 1)[0]
    try:
        return sign * int(head)
    except ValueError:
        return None


def parse_works_period(wp):
    """Parse works_period into (first, last). Returns (None, None) on fail.

    Examples:
      "1946"        -> (1946, 1946)
      "1892-1964"   -> (1892, 1964)
      "-1250"       -> (-1250, -1250)
      "-58--43"     -> (-58, -43)
      "-600-1893"   -> (-600, 1893)
    """
    if not wp:
        return None, None
    s = str(wp).strip()
    if not s:
        return None, None
    if s.startswith("-"):
        rest = s[1:]
        idx = rest.find("-")
        if idx == -1:
            try:
                v = -int(rest)
                return v, v
            except ValueError:
                return None, None
        try:
            start = -int(rest[:idx])
        except ValueError:
            return None, None
        end_str = rest[idx + 1 :]
        if not end_str:
            return start, start
        if end_str.startswith("-"):
            try:
                return start, -int(end_str[1:])
            except ValueError:
                return start, start
        try:
            return start, int(end_str)
        except ValueError:
            return start, start
    if "-" in s:
        a, b = s.split("-", 1)
        try:
            return int(a), int(b)
        except ValueError:
            return None, None
    try:
        v = int(s)
        return v, v
    except ValueError:
        return None, None


def parse_floruit_wikipedia(s):
    """floruit_from_wikipedia is either a single year ("1996") or a span
    ("1846-1900"). Returns (start, end) — both equal for single years."""
    return parse_works_period(s)


# --------------------------------------------------------------------------
# Precision helpers
# --------------------------------------------------------------------------


def is_year_precise(p):
    return p is not None and p >= 9


def is_decade_precise(p):
    return p == 8


def is_century_precise(p):
    return p is not None and 5 <= p <= 7


def precision_class(p):
    if p is None:
        return ""
    if p >= 9:
        return "year"
    if p == 8:
        return "decade"
    if 5 <= p <= 7:
        return "century"
    return "millennium"


# --------------------------------------------------------------------------
# Century labels (kept consistent with previous output)
# --------------------------------------------------------------------------


def _ordinal(n):
    if n % 100 in (11, 12, 13):
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def century_label(year):
    if year > 0:
        n = (year + 99) // 100
        return f"{_ordinal(n)} c. AD"
    if year < 0:
        n = (-year + 99) // 100
        return f"{_ordinal(n)} c. BC"
    return "1st c. AD"


def century_period_label(start, end):
    cs, ce = century_label(start), century_label(end)
    if cs == ce:
        return cs
    if cs.endswith(" c. AD") and ce.endswith(" c. AD"):
        return f"{cs[:-6]}-{ce[:-6]} c. AD"
    if cs.endswith(" c. BC") and ce.endswith(" c. BC"):
        return f"{cs[:-6]}-{ce[:-6]} c. BC"
    return f"{cs} - {ce}"


def century_bounds(year):
    if year > 0:
        n = (year + 99) // 100
        return ((n - 1) * 100 + 1, n * 100)
    if year < 0:
        n = (-year + 99) // 100
        return (-(n * 100), -((n - 1) * 100 + 1))
    return (1, 100)


def two_century_window(year_a, year_b):
    sa, ea = century_bounds(year_a)
    sb, eb = century_bounds(year_b)
    if sa > sb:
        sa, ea, sb, eb = sb, eb, sa, ea
    mid_a = sa + 50
    mid_b = sb + 49
    return (mid_a, mid_b)


# --------------------------------------------------------------------------
# Window builders
# --------------------------------------------------------------------------


def expand_around_floruit(fy, lo, hi, birth_year=None, death_year=None):
    """Active-period window anchored on a single floruit year.

    With a known birth year we measure age and place the floruit at start
    (anchor before range), end (anchor after range), or inside the [lo, hi]
    productive years. Without a birth year we span [fy, fy + (hi - lo)].
    """
    span = hi - lo
    if birth_year is not None:
        age = fy - birth_year
        if age <= lo:
            start, end = fy, birth_year + hi
        elif age >= hi:
            start, end = birth_year + lo, fy
        else:
            start = birth_year + lo
            end = birth_year + hi
    else:
        start, end = fy, fy + span
    if death_year is not None and death_year < end:
        end = death_year
    end = min(end, CURRENT_YEAR)
    start = min(start, end)
    return start, end


def window_birth_death(b, d, lo, hi):
    if b + lo > CURRENT_YEAR:
        return None, None
    start = b + lo
    end = min(b + hi, d, CURRENT_YEAR)
    if start > end:
        end = min(d, CURRENT_YEAR)
        start = min(start, end)
    return start, end


def window_birth_only(b, lo, hi):
    if b + lo > CURRENT_YEAR:
        return None, None
    return b + lo, min(b + hi, CURRENT_YEAR)


# --------------------------------------------------------------------------
# Candidate builder
# --------------------------------------------------------------------------


# (priority, method, source, precision_class, estimated)
def _cand(priority, start, end, method, source, precision, estimated):
    return (priority, start, end, method, source, precision, estimated)


def compute_floruit(row, cv_category=None):
    """Return (start, end, method, source, precision_class, estimated, label).

    `row` is a tuple matching QUERY_COLS. `cv_category` is the individual's
    CV level1 occupation (used to pick the productive-age window).
    """
    lo, hi = productive_age(cv_category)

    (
        wikidata_id,
        name_en,
        description_en,
        birthdate,
        birthdate_precision,
        deathdate,
        deathdate_precision,
        floruit_date,
        floruit_precision,
        floruit_year,
        dates_in_description,
        birthdate_in_description,
        deathdate_in_description,
        floruit_year_in_description,
        birthdate_from_CV,
        deathdate_from_CV,
        birthdate_from_wikipedia,
        deathdate_from_wikipedia,
        floruit_from_wikipedia,
        birthdate_from_life_expectancy,
        deathdate_from_life_expectancy,
        works_period,
    ) = row

    # Parse year sources
    bd_year = parse_year(birthdate)
    dd_year = parse_year(deathdate)
    fl_year = floruit_year if floruit_year is not None else parse_year(floruit_date)
    desc_b = birthdate_in_description
    desc_d = deathdate_in_description
    desc_f = floruit_year_in_description
    has_desc_birthdeath = desc_b is not None and desc_d is not None
    cv_b = parse_year(birthdate_from_CV)
    cv_d = parse_year(deathdate_from_CV)
    wp_b = parse_year(birthdate_from_wikipedia)
    wp_d = parse_year(deathdate_from_wikipedia)
    est_b = parse_year(birthdate_from_life_expectancy)
    est_d = parse_year(deathdate_from_life_expectancy)
    works_first, works_last = parse_works_period(works_period)
    wp_f_a, wp_f_b = parse_floruit_wikipedia(floruit_from_wikipedia)

    # Drop contradicted Wikidata pair (birth after death)
    if bd_year is not None and dd_year is not None and bd_year > dd_year:
        dd_year = None

    # Best-known birth year for under-30 cutoff and floruit anchoring
    best_birth = None
    for cand in (
        bd_year if is_year_precise(birthdate_precision) else None,
        desc_b,
        cv_b,
        wp_b,
        est_b,
        bd_year,  # accept coarser as last resort
    ):
        if cand is not None:
            best_birth = cand
            break
    best_death = None
    for cand in (
        dd_year if is_year_precise(deathdate_precision) else None,
        desc_d,
        cv_d,
        wp_d,
        est_d,
        dd_year,
    ):
        if cand is not None:
            best_death = cand
            break

    has_explicit_floruit = (
        fl_year is not None
        or (desc_f is not None and not has_desc_birthdeath)
        or wp_f_a is not None
        or works_first is not None
    )

    # Under-cutoff: best birth year is too recent to have entered productive years
    if (
        best_birth is not None
        and best_birth > UNDER_FLORUIT_BIRTH_CUTOFF
        and not has_explicit_floruit
    ):
        return (None, None, "under_30", "none", "", False, None)

    candidates = []

    # ---------- Tier A: year-precise ----------

    # A1 — Wikidata floruit property, year-precise
    if fl_year is not None and is_year_precise(floruit_precision):
        s, e = expand_around_floruit(fl_year, lo, hi, bd_year, dd_year)
        candidates.append(
            _cand(100, s, e, "floruit_property", "wikidata_property", "year", False)
        )

    # A2 — description, single floruit (no birth/death in description)
    if desc_f is not None and not has_desc_birthdeath:
        s, e = expand_around_floruit(desc_f, lo, hi, bd_year, dd_year)
        candidates.append(
            _cand(
                110, s, e, "floruit_description", "wikidata_description", "year", False
            )
        )

    # A3 — wikipedia floruit (single year or span)
    if wp_f_a is not None:
        if wp_f_b is not None and wp_f_a != wp_f_b:
            candidates.append(
                _cand(
                    115,
                    wp_f_a,
                    wp_f_b,
                    "floruit_wikipedia_span",
                    "wikipedia",
                    "year",
                    False,
                )
            )
        else:
            s, e = expand_around_floruit(wp_f_a, lo, hi, bd_year, dd_year)
            candidates.append(
                _cand(118, s, e, "floruit_wikipedia", "wikipedia", "year", False)
            )

    # A4 / A5 — works
    if works_first is not None:
        if works_last is not None and works_first != works_last:
            candidates.append(
                _cand(
                    120, works_first, works_last, "works_span", "works", "year", False
                )
            )
        else:
            s, e = expand_around_floruit(works_first, lo, hi, bd_year, dd_year)
            candidates.append(_cand(125, s, e, "works_single", "works", "year", False))

    # A6 — Wikidata birth+death (year-precise)
    if (
        bd_year is not None
        and is_year_precise(birthdate_precision)
        and dd_year is not None
        and is_year_precise(deathdate_precision)
    ):
        s, e = window_birth_death(bd_year, dd_year, lo, hi)
        if s is not None:
            candidates.append(
                _cand(
                    130,
                    s,
                    e,
                    "birth_death_property",
                    "wikidata_property",
                    "year",
                    False,
                )
            )

    # A7 — description birth+death
    if has_desc_birthdeath:
        s, e = window_birth_death(desc_b, desc_d, lo, hi)
        if s is not None:
            candidates.append(
                _cand(
                    140,
                    s,
                    e,
                    "birth_death_description",
                    "wikidata_description",
                    "year",
                    False,
                )
            )

    # A8 — CV birth+death
    if cv_b is not None and cv_d is not None:
        s, e = window_birth_death(cv_b, cv_d, lo, hi)
        if s is not None:
            candidates.append(
                _cand(150, s, e, "birth_death_cv", "cv_database", "year", False)
            )

    # A9 — wikipedia birth+death
    if wp_b is not None and wp_d is not None:
        s, e = window_birth_death(wp_b, wp_d, lo, hi)
        if s is not None:
            candidates.append(
                _cand(155, s, e, "birth_death_wikipedia", "wikipedia", "year", False)
            )

    # A10 — birth-only (year-precise from any source, in priority order)
    if dd_year is None:  # only relevant when death isn't known
        if bd_year is not None and is_year_precise(birthdate_precision):
            s, e = window_birth_only(bd_year, lo, hi)
            if s is not None:
                candidates.append(
                    _cand(
                        160,
                        s,
                        e,
                        "birth_only_property",
                        "wikidata_property",
                        "year",
                        False,
                    )
                )
        if desc_b is not None and not has_desc_birthdeath:
            s, e = window_birth_only(desc_b, lo, hi)
            if s is not None:
                candidates.append(
                    _cand(
                        162,
                        s,
                        e,
                        "birth_only_description",
                        "wikidata_description",
                        "year",
                        False,
                    )
                )
        if cv_b is not None and cv_d is None:
            s, e = window_birth_only(cv_b, lo, hi)
            if s is not None:
                candidates.append(
                    _cand(164, s, e, "birth_only_cv", "cv_database", "year", False)
                )
        if wp_b is not None and wp_d is None:
            s, e = window_birth_only(wp_b, lo, hi)
            if s is not None:
                candidates.append(
                    _cand(166, s, e, "birth_only_wikipedia", "wikipedia", "year", False)
                )

    # No death-only rule per the floruit guidelines: an isolated death year
    # is not enough to anchor an active period — we fall through to "no_data".

    # ---------- Tier B: coarse (decade/century) ----------

    # B0 — decade-precise floruit (still better than century)
    if fl_year is not None and is_decade_precise(floruit_precision):
        s, e = expand_around_floruit(fl_year, lo, hi, bd_year, dd_year)
        candidates.append(
            _cand(
                200,
                s,
                e,
                "floruit_property_decade",
                "wikidata_property",
                "decade",
                False,
            )
        )

    # B1 — century-precise floruit
    if fl_year is not None and is_century_precise(floruit_precision):
        s, e = century_bounds(fl_year)
        candidates.append(
            _cand(
                210,
                s,
                e,
                "floruit_property_century",
                "wikidata_property",
                "century",
                False,
            )
        )

    # B2 — century-precise birth+death from Wikidata
    bc = bd_year is not None and is_century_precise(birthdate_precision)
    dc = dd_year is not None and is_century_precise(deathdate_precision)
    if bc and dc:
        if century_bounds(bd_year) == century_bounds(dd_year):
            s, e = century_bounds(bd_year)
        else:
            s, e = two_century_window(bd_year, dd_year)
        candidates.append(
            _cand(
                220, s, e, "birth_death_century", "wikidata_property", "century", False
            )
        )
    elif bc:
        s, e = century_bounds(bd_year)
        candidates.append(
            _cand(222, s, e, "birth_century", "wikidata_property", "century", False)
        )
    elif dc:
        s, e = century_bounds(dd_year)
        candidates.append(
            _cand(223, s, e, "death_century", "wikidata_property", "century", False)
        )

    # ---------- Tier C: estimated ----------

    # C1 — estimated death paired with year-precise birth
    if (
        bd_year is not None
        and is_year_precise(birthdate_precision)
        and dd_year is None
        and est_d is not None
    ):
        s, e = window_birth_death(bd_year, est_d, lo, hi)
        if s is not None:
            candidates.append(
                _cand(
                    305,
                    s,
                    e,
                    "birth_death_estimated_death",
                    "life_expectancy",
                    "year",
                    True,
                )
            )

    # C2 — estimated birth paired with year-precise death
    if (
        dd_year is not None
        and is_year_precise(deathdate_precision)
        and bd_year is None
        and est_b is not None
    ):
        s, e = window_birth_death(est_b, dd_year, lo, hi)
        if s is not None:
            candidates.append(
                _cand(
                    306,
                    s,
                    e,
                    "birth_death_estimated_birth",
                    "life_expectancy",
                    "year",
                    True,
                )
            )

    # C3 — both estimated (very rare, but covered for completeness)
    if est_b is not None and est_d is not None and bd_year is None and dd_year is None:
        s, e = window_birth_death(est_b, est_d, lo, hi)
        if s is not None:
            candidates.append(
                _cand(
                    310, s, e, "birth_death_estimated", "life_expectancy", "year", True
                )
            )

    if not candidates:
        return (None, None, "no_data", "none", "", False, None)

    candidates.sort(key=lambda c: c[0])
    _p, s, e, method, source, prec, est = candidates[0]
    if prec == "century":
        label = century_period_label(s, e)
    else:
        label = f"{s}-{e}" if s != e else str(s)
    return (s, e, method, source, prec, est, label)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def load_cv_categories():
    """{wikidata_id: level1 occupation category}, dropping blank/Missing rows."""
    conn = duckdb.connect()
    df = conn.execute(f"""
        SELECT TRIM(wikidata_code)   AS wikidata_id,
               TRIM(level1_main_occ) AS category
        FROM   read_csv_auto('{CV_PATH}', compression='gzip')
        WHERE  wikidata_code   IS NOT NULL AND TRIM(wikidata_code)   <> ''
          AND  level1_main_occ IS NOT NULL
          AND  TRIM(level1_main_occ) NOT IN ('', 'Missing')
    """).fetchall()
    conn.close()
    return dict(df)


def run(sample_size=None):
    log(f"[01] Reading individuals from {DUCKDB_PATH}")
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    cv_categories = load_cv_categories()
    log(f"[01] Loaded {len(cv_categories):,} CV occupation entries")

    conn = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    cols_csv = ", ".join(QUERY_COLS)
    if sample_size is not None:
        sql = (
            f"SELECT {cols_csv} FROM individuals "
            f"USING SAMPLE {sample_size} ROWS (reservoir, 42)"
        )
        total = sample_size
    else:
        sql = f"SELECT {cols_csv} FROM individuals"
        total = conn.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]

    log(f"[01] Computing floruit period for {total:,} rows")

    method_counts = {}
    source_counts = {}
    n_with = 0

    t0 = time.time()
    cur = conn.execute(sql)

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(OUT_COLS)

        BATCH = 100_000
        with tqdm(total=total, unit="row", desc="01") as pbar:
            while True:
                rows = cur.fetchmany(BATCH)
                if not rows:
                    break
                out_buf = []
                for r in rows:
                    start, end, method, source, prec, estimated, label = (
                        compute_floruit(r, cv_categories.get(r[0]))
                    )
                    method_counts[method] = method_counts.get(method, 0) + 1
                    source_counts[source] = source_counts.get(source, 0) + 1
                    if start is not None:
                        n_with += 1
                    out_buf.append(
                        (
                            r[0],  # wikidata_id
                            r[1],  # name_en
                            parse_year(r[3]),  # birth_year
                            precision_class(r[4]),  # birth_precision
                            parse_year(r[5]),  # death_year
                            precision_class(r[6]),  # death_precision
                            (
                                r[9] if r[9] is not None else parse_year(r[7])
                            ),  # floruit_year
                            precision_class(r[8]),  # floruit_precision_class
                            r[13],  # floruit_year_in_description
                            r[21],  # works_period
                            start,
                            end,
                            label,
                            method,
                            source,
                            prec,
                            1 if estimated else 0,
                        )
                    )
                writer.writerows(out_buf)
                pbar.update(len(rows))

    conn.close()
    dt = time.time() - t0
    log(f"[01] Wrote {n_with:,}/{total:,} rows with floruit period -> {OUTPUT_CSV}")
    log(f"[01] Elapsed {dt:,.1f}s ({total / max(dt,1e-9):,.0f} rows/s)")

    log("[01] Methods:")
    for k, v in sorted(method_counts.items(), key=lambda kv: -kv[1]):
        log(f"     {k:38s} {v:>10,}")
    log("[01] Sources:")
    for k, v in sorted(source_counts.items(), key=lambda kv: -kv[1]):
        log(f"     {k:38s} {v:>10,}")


def insert_into_db():
    """Replace `individuals_floruit_period` in humans_clean.duckdb with the
    contents of OUTPUT_CSV. The schema mirrors the previous table (so
    downstream cliopatria + consolidated_database queries keep working) and
    extends it with `source`, `precision_class`, `estimated`."""
    if not OUTPUT_CSV.exists():
        raise SystemExit(f"CSV not found: {OUTPUT_CSV} — run --full first")

    log(f"[01] Replacing individuals_floruit_period in {DUCKDB_PATH}")
    conn = duckdb.connect(str(DUCKDB_PATH))
    try:
        before = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name='individuals_floruit_period'"
        ).fetchone()[0]
        if before:
            existing = conn.execute(
                "SELECT COUNT(*) FROM individuals_floruit_period"
            ).fetchone()[0]
            log(f"[01] dropping old individuals_floruit_period ({existing:,} rows)")

        conn.execute("DROP TABLE IF EXISTS individuals_floruit_period")
        conn.execute(f"""
            CREATE TABLE individuals_floruit_period AS
            SELECT
              fp.wikidata_id,
              fp.name_en,
              i.birthdate,
              i.birthdate_precision,
              fp.birth_year,
              i.deathdate,
              i.deathdate_precision,
              fp.death_year,
              i.floruit_date,
              i.floruit_precision,
              COALESCE(i.floruit_year, fp.floruit_year_property) AS floruit_year,
              fp.floruit_period,
              fp.floruit_period_start,
              fp.floruit_period_end,
              fp.method,
              fp.source,
              fp.precision_class,
              fp.estimated,
              fp.works_period
            FROM read_csv_auto('{OUTPUT_CSV}', header=true,
                               nullstr='', sample_size=-1) fp
            LEFT JOIN individuals i USING (wikidata_id)
        """)

        for sql in (
            "CREATE INDEX idx_fp_method ON individuals_floruit_period(method)",
            "CREATE INDEX idx_fp_source ON individuals_floruit_period(source)",
            "CREATE INDEX idx_fp_birth_year ON individuals_floruit_period(birth_year)",
            "CREATE INDEX idx_fp_death_year ON individuals_floruit_period(death_year)",
            "CREATE INDEX idx_fp_start ON individuals_floruit_period(floruit_period_start)",
            "CREATE INDEX idx_fp_end ON individuals_floruit_period(floruit_period_end)",
            "CREATE UNIQUE INDEX idx_fp_qid ON individuals_floruit_period(wikidata_id)",
        ):
            conn.execute(sql)

        n = conn.execute("SELECT COUNT(*) FROM individuals_floruit_period").fetchone()[
            0
        ]
        with_p = conn.execute(
            "SELECT COUNT(*) FROM individuals_floruit_period "
            "WHERE floruit_period_start IS NOT NULL"
        ).fetchone()[0]
        log(f"[01] inserted {n:,} rows ({with_p:,} with a floruit period)")
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="run on all individuals")
    ap.add_argument(
        "--sample",
        type=int,
        default=10_000,
        help="number of rows to sample when not --full",
    )
    ap.add_argument(
        "--insert-db",
        action="store_true",
        help="replace individuals_floruit_period in humans_clean.duckdb "
        "with the current CSV (does NOT recompute it)",
    )
    args = ap.parse_args()

    if args.insert_db and not args.full:
        # Skip the recompute, just push CSV → DuckDB.
        insert_into_db()
        return

    if args.full:
        run(sample_size=None)
    else:
        run(sample_size=args.sample)

    if args.insert_db:
        insert_into_db()


if __name__ == "__main__":
    main()
