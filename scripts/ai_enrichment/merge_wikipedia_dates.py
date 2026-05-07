"""
Merge Wikipedia/Gemini date extractions into data/humans_clean.sqlite3.

Adds three columns to the `individuals` table (idempotent — skips if present):
  - birthdate_from_wikipedia      TEXT
  - deathdate_from_wikipedia      TEXT
  - floruit_from_wikipedia        TEXT

Format rules
------------
year precision      → "1452"           (single year)
year-range          → "1450-1480"      (start-end, both populated)
decade precision    → "1450s"
century precision   → "14th"           (full century 1301-1400 or similar)
first-half century  → "f 14th"         (1301-1350 ish)
second-half century → "s 14th"         (1351-1400 ish)
millennium          → "2nd millennium"
BCE centuries       → "5th BCE"

Usage
-----
    .venv/bin/python scripts/ai_enrichment/merge_wikipedia_dates.py \
        scripts/no_date_extraction_test_20260506_225749.csv
"""

from __future__ import annotations

import csv
import math
import sqlite3
import sys
from pathlib import Path

from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB = PROJECT_ROOT / "data" / "humans_clean.sqlite3"

NEW_COLUMNS = [
    "birthdate_from_wikipedia",
    "deathdate_from_wikipedia",
    "floruit_from_wikipedia",
]


# ---------- formatting helpers --------------------------------------------


def ord_suffix(n: int) -> str:
    n = abs(n)
    if 10 <= n % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def century_of(year: int) -> int:
    """Century number (1-indexed) for `year`. Returns positive for both
    CE and BCE; the caller decides whether to suffix " BCE"."""
    return math.ceil(abs(year) / 100)


def fmt_century(century: int, half: str | None, bce: bool) -> str:
    """`half` is "f", "s", or None."""
    base = f"{century}{ord_suffix(century)}"
    if bce:
        base += " BCE"
    if half:
        return f"{half} {base}"
    return base


def parse_int(v) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(v))  # CSV may serialise as "1452.0"
    except (ValueError, TypeError):
        return None


def fmt_birth_or_death(year_str: str, precision: str | None) -> str | None:
    year = parse_int(year_str)
    if year is None:
        return None
    p = (precision or "").lower()
    if p == "century":
        return fmt_century(century_of(year), None, year < 0)
    if p == "decade":
        decade = (year // 10) * 10
        return f"{decade}s"
    if p == "millennium":
        m = math.ceil(abs(year) / 1000)
        suffix = " BCE" if year < 0 else ""
        return f"{m}{ord_suffix(m)} millennium{suffix}"
    return str(year)


def fmt_floruit(start_s: str, end_s: str, precision: str | None) -> str | None:
    start = parse_int(start_s)
    end = parse_int(end_s)
    if start is None and end is None:
        return None
    p = (precision or "").lower()

    if p == "century":
        anchor = end if end is not None else start
        century = century_of(anchor)
        bce = anchor < 0
        if start is None or end is None:
            return fmt_century(century, None, bce)
        # Determine which half of the century the [start, end] window covers.
        # Positive years: century N = years (N-1)*100+1 .. N*100
        if not bce:
            century_start = (century - 1) * 100 + 1
            offset_start = start - century_start  # 0..99
            offset_end = end - century_start  # 0..99
        else:
            # BCE: century 5 BCE = -500..-401. start is more negative, end less.
            century_start = -century * 100  # most-negative end
            offset_start = abs(start - century_start)
            offset_end = abs(end - century_start)
        span = end - start + 1
        if span >= 90:
            return fmt_century(century, None, bce)
        if offset_end <= 55:
            return fmt_century(century, "f", bce)
        if offset_start >= 45:
            return fmt_century(century, "s", bce)
        return fmt_century(century, None, bce)

    if p == "decade":
        anchor = start if start is not None else end
        decade = (anchor // 10) * 10
        return f"{decade}s"

    if p == "millennium":
        anchor = start if start is not None else end
        m = math.ceil(abs(anchor) / 1000)
        suffix = " BCE" if anchor < 0 else ""
        return f"{m}{ord_suffix(m)} millennium{suffix}"

    # year precision (default)
    if start is not None and end is not None and start != end:
        return f"{start}-{end}"
    return str(start if start is not None else end)


# ---------- DB writer -----------------------------------------------------


def ensure_columns(con: sqlite3.Connection) -> None:
    existing = {r[1] for r in con.execute("PRAGMA table_info(individuals)").fetchall()}
    for col in NEW_COLUMNS:
        if col not in existing:
            con.execute(f"ALTER TABLE individuals ADD COLUMN {col} TEXT")
            print(f"  + added column {col}")
        else:
            print(f"  - column {col} already present (will overwrite)")
    con.commit()


def main(csv_path: Path) -> int:
    if not csv_path.exists():
        print(f"ERROR: CSV not found: {csv_path}")
        return 1
    if not DB.exists():
        print(f"ERROR: DB not found: {DB}")
        return 1

    print(f"DB  : {DB}")
    print(f"CSV : {csv_path}")
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    print("Ensuring columns exist:")
    ensure_columns(con)

    rows = []
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r.get("error"):
                continue
            qid = r["wikidata_id"]
            b = fmt_birth_or_death(r.get("birthdate"), r.get("birthdate_precision"))
            d = fmt_birth_or_death(r.get("deathdate"), r.get("deathdate_precision"))
            fl = fmt_floruit(
                r.get("floruit_period_start"),
                r.get("floruit_period_end"),
                r.get("floruit_precision"),
            )
            if b is None and d is None and fl is None:
                continue
            rows.append((b, d, fl, qid))

    print(f"\nrows ready to update: {len(rows):,}")
    if not rows:
        return 0

    sql = (
        "UPDATE individuals SET "
        "birthdate_from_wikipedia = ?, "
        "deathdate_from_wikipedia = ?, "
        "floruit_from_wikipedia   = ? "
        "WHERE wikidata_id = ?"
    )

    BATCH = 1000
    updated = 0
    with con:
        cur = con.cursor()
        for i in tqdm(range(0, len(rows), BATCH), desc="updating", unit="batch"):
            chunk = rows[i : i + BATCH]
            cur.executemany(sql, chunk)
            updated += cur.rowcount if cur.rowcount > 0 else len(chunk)

    # report final populated counts
    counts = con.execute(
        "SELECT "
        "  COUNT(birthdate_from_wikipedia), "
        "  COUNT(deathdate_from_wikipedia), "
        "  COUNT(floruit_from_wikipedia)   "
        "FROM individuals"
    ).fetchone()
    print(
        f"\npopulated rows: birth={counts[0]:,} death={counts[1]:,} floruit={counts[2]:,}"
    )

    # show 8 random samples to spot-check formatting
    sample = con.execute(
        "SELECT wikidata_id, name_en, birthdate_from_wikipedia, "
        "deathdate_from_wikipedia, floruit_from_wikipedia "
        "FROM individuals "
        "WHERE floruit_from_wikipedia IS NOT NULL "
        "ORDER BY RANDOM() LIMIT 8"
    ).fetchall()
    print("\nformatting spot-check:")
    for s in sample:
        print(f"  {s[0]:>14}  {s[1] or '':30.30}  birth={s[2]!s:>10}  death={s[3]!s:>10}  floruit={s[4]!s:>14}")

    con.close()
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: merge_wikipedia_dates.py <csv_path>")
        sys.exit(1)
    sys.exit(main(Path(sys.argv[1])))
