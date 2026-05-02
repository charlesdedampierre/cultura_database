"""60 — Build individuals_floruit_period.

Mirrors `enhance_db/src/bin/60_create_individuals_floruit_period.rs`.

Reads floruit (P1317) directly from `individuals` (since 2026-05; the
former standalone `individuals_floruit` table was retired) and derives a
floruit_period using the rules from the paper. Each row is tagged with
`method` in {floruit, birth, death, birth_century, death_century}.

Precision codes (Wikidata): 11=day, 10=month, 9=year, 8=decade,
7=century, 6=millennium. Year-precise = >=9; decade = 8;
century-or-coarser = in [5,7].

Default span = ages 30..55 (FLORUIT_LO_OFFSET..FLORUIT_HI_OFFSET).
Periods are capped at CURRENT_YEAR; people not yet 30 get no floruit.

Usage
-----
    python3 60_create_individuals_floruit_period.py
    python3 60_create_individuals_floruit_period.py --full
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from tqdm import tqdm

from common import insert_rows, log, open_db, parse_run_mode, parse_year

FLORUIT_LO_OFFSET = 30
FLORUIT_HI_OFFSET = 55
FLORUIT_SPAN = FLORUIT_HI_OFFSET - FLORUIT_LO_OFFSET  # 25
DEATH_ONLY_LOOKBACK = 25
CURRENT_YEAR = 2026


def ordinal(n: int) -> str:
    if n % 100 in (11, 12, 13):
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def century_label(year: int) -> str:
    if year > 0:
        n = (year + 99) // 100
        return f"{ordinal(n)} c. AD"
    if year < 0:
        n = (-year + 99) // 100
        return f"{ordinal(n)} c. BC"
    return "1st c. AD"


def century_period_label(start: int, end: int) -> str:
    cs = century_label(start)
    ce = century_label(end)
    if cs == ce:
        return cs
    if cs.endswith(" c. AD") and ce.endswith(" c. AD"):
        return f"{cs[:-6]}-{ce[:-6]} c. AD"
    if cs.endswith(" c. BC") and ce.endswith(" c. BC"):
        return f"{cs[:-6]}-{ce[:-6]} c. BC"
    return f"{cs} - {ce}"


def century_bounds(year: int) -> tuple[int, int]:
    """Return the inclusive (first_year, last_year) of the century that
    contains `year`. 11th c. AD -> (1001, 1100); 1st c. BC -> (-100, -1)."""
    if year > 0:
        n = (year + 99) // 100
        return ((n - 1) * 100 + 1, n * 100)
    if year < 0:
        n = (-year + 99) // 100
        return (-(n * 100), -((n - 1) * 100 + 1))
    return (1, 100)


def two_century_window(year_a: int, year_b: int) -> tuple[int, int]:
    """Apply the new two-century rule: the second half of the first
    century + the first half of the last century. Works regardless of
    whether the two centuries are adjacent or further apart."""
    sa, ea = century_bounds(year_a)
    sb, eb = century_bounds(year_b)
    if sa > sb:
        sa, ea, sb, eb = sb, eb, sa, ea
    # Second half of first century -> mid_a..ea ; first half of last -> sb..mid_b
    mid_a = sa + 50
    mid_b = sb + 49
    return (mid_a, mid_b)


def _decade_precise(p):
    return p is not None and p >= 8


def _century_precise(p):
    return p is not None and 5 <= p <= 7


def compute_floruit(birth_year, birth_prec, death_year, death_prec,
                    floruit_year, floruit_prec):
    birth_usable = birth_year is not None and _decade_precise(birth_prec)
    death_usable = death_year is not None and _decade_precise(death_prec)
    floruit_usable = floruit_year is not None and _decade_precise(floruit_prec)

    if floruit_usable:
        fy = floruit_year
        start = fy
        end = fy + FLORUIT_SPAN
        if death_usable and death_year < end:
            end = death_year
        end = min(end, CURRENT_YEAR)
        start = min(start, end)
        return (start, end, "floruit")

    if birth_usable and death_usable:
        b = birth_year
        d = death_year
        if b + FLORUIT_LO_OFFSET > CURRENT_YEAR:
            return (None, None, "")
        start = b + FLORUIT_LO_OFFSET
        end = min(b + FLORUIT_HI_OFFSET, d, CURRENT_YEAR)
        if start <= end:
            return (start, end, "birth")
        end2 = min(d, CURRENT_YEAR)
        return (min(end2, start), end2, "birth")

    if birth_usable and not death_usable:
        b = birth_year
        if b + FLORUIT_LO_OFFSET > CURRENT_YEAR:
            return (None, None, "")
        start = b + FLORUIT_LO_OFFSET
        end = min(b + FLORUIT_HI_OFFSET, CURRENT_YEAR)
        return (min(start, end), end, "birth")

    if death_usable and not birth_usable:
        d = death_year
        end = min(d, CURRENT_YEAR)
        return (end - DEATH_ONLY_LOOKBACK, end, "death")

    # Century-precision rules (2026-05): a single century -> the entire
    # 100-year span of that century; two centuries -> second half of the
    # first + first half of the last (see two_century_window()).
    if floruit_year is not None and _century_precise(floruit_prec):
        s, e = century_bounds(floruit_year)
        return (s, e, "floruit")

    bc = birth_year is not None and _century_precise(birth_prec)
    dc = death_year is not None and _century_precise(death_prec)

    if bc and dc:
        s_b, e_b = century_bounds(birth_year)
        s_d, e_d = century_bounds(death_year)
        if (s_b, e_b) == (s_d, e_d):
            return (s_b, e_b, "birth_century")
        s, e = two_century_window(birth_year, death_year)
        return (s, e, "birth_century")

    if bc:
        s, e = century_bounds(birth_year)
        return (s, e, "birth_century")

    if dc:
        s, e = century_bounds(death_year)
        return (s, e, "death_century")

    return (None, None, "")


def run(conn: sqlite3.Connection) -> int:
    log("[DB] 60: Build individuals_floruit_period...")
    # Floruit lives on the `individuals` table since 2026-05 (no separate
    # individuals_floruit table any more).
    floruit_map: dict[str, tuple] = {}
    for qid, fd, fp, fy in conn.execute(
        "SELECT wikidata_id, floruit_date, floruit_precision, floruit_year "
        "FROM individuals WHERE floruit_year IS NOT NULL "
        "   OR floruit_date IS NOT NULL"
    ):
        floruit_map[qid] = (fd, fp, fy)

    conn.execute("DROP TABLE IF EXISTS individuals_floruit_period")
    conn.execute(
        """
        CREATE TABLE individuals_floruit_period (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            birthdate TEXT,
            birthdate_precision INTEGER,
            birth_year INTEGER,
            deathdate TEXT,
            deathdate_precision INTEGER,
            death_year INTEGER,
            floruit_date TEXT,
            floruit_precision INTEGER,
            floruit_year INTEGER,
            floruit_period TEXT,
            floruit_period_start INTEGER,
            floruit_period_end INTEGER,
            method TEXT
        )
        """
    )

    total = conn.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]
    cur = conn.cursor()
    cur.execute("BEGIN")
    n = 0
    contradicted = 0
    for qid, name, birthdate, bprec, deathdate, dprec in tqdm(
        conn.execute(
            "SELECT wikidata_id, name_en, birthdate, birthdate_precision, "
            "deathdate, deathdate_precision FROM individuals"
        ),
        total=total, desc="60", unit="row",
    ):
        birth_year = parse_year(birthdate) if birthdate else None
        death_year = parse_year(deathdate) if deathdate else None
        if birth_year is not None and death_year is not None and birth_year > death_year:
            contradicted += 1
            death_year = None
        fdate, fprec, fyear = floruit_map.get(qid, (None, None, None))

        start, end, method = compute_floruit(
            birth_year, bprec, death_year, dprec, fyear, fprec
        )
        century_display = method in ("birth_century", "death_century") or (
            method == "floruit" and fprec is not None and 5 <= fprec <= 7
        )
        if start is not None and end is not None:
            period = (
                century_period_label(start, end)
                if century_display
                else f"{start}-{end}"
            )
        else:
            period = None

        cur.execute(
            "INSERT INTO individuals_floruit_period "
            "(wikidata_id, name_en, birthdate, birthdate_precision, birth_year, "
            "deathdate, deathdate_precision, death_year, floruit_date, "
            "floruit_precision, floruit_year, floruit_period, "
            "floruit_period_start, floruit_period_end, method) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (qid, name, birthdate, bprec, birth_year,
             deathdate, dprec, death_year,
             fdate, fprec, fyear,
             period, start, end, method or None),
        )
        n += 1
        if n % 50_000 == 0:
            conn.commit()
            cur.execute("BEGIN")
    conn.commit()
    log(f"[DB] inserted {n} (contradicted dropped: {contradicted})")

    for sql in (
        "CREATE INDEX IF NOT EXISTS idx_fp_method ON individuals_floruit_period(method)",
        "CREATE INDEX IF NOT EXISTS idx_fp_birth_year ON individuals_floruit_period(birth_year)",
        "CREATE INDEX IF NOT EXISTS idx_fp_death_year ON individuals_floruit_period(death_year)",
        "CREATE INDEX IF NOT EXISTS idx_fp_start ON individuals_floruit_period(floruit_period_start)",
        "CREATE INDEX IF NOT EXISTS idx_fp_end ON individuals_floruit_period(floruit_period_end)",
    ):
        conn.execute(sql)
    conn.commit()
    return n


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, "
                "name_en TEXT, birthdate TEXT, birthdate_precision INTEGER, "
                "deathdate TEXT, deathdate_precision INTEGER, "
                "floruit_date TEXT, floruit_precision INTEGER, floruit_year INTEGER)"
            )
            insert_rows(seed, "individuals", [
                {"wikidata_id": "Q1", "name_en": "Born1880",
                 "birthdate": "+1880-01-01", "birthdate_precision": 9,
                 "deathdate": "+1955-06-30", "deathdate_precision": 9,
                 "floruit_date": "+1910-01-01", "floruit_precision": 9,
                 "floruit_year": 1910},
                {"wikidata_id": "Q2", "name_en": "AncientRome",
                 "birthdate": "-0050-01-01", "birthdate_precision": 9,
                 "deathdate": None, "deathdate_precision": None,
                 "floruit_date": None, "floruit_precision": None,
                 "floruit_year": None},
                {"wikidata_id": "Q3", "name_en": "MedievalCent",
                 "birthdate": "+1100-01-01", "birthdate_precision": 7,
                 "deathdate": None, "deathdate_precision": None,
                 "floruit_date": None, "floruit_precision": None,
                 "floruit_year": None},
                {"wikidata_id": "Q4", "name_en": "TooYoung",
                 "birthdate": "+2010-01-01", "birthdate_precision": 9,
                 "deathdate": None, "deathdate_precision": None,
                 "floruit_date": None, "floruit_precision": None,
                 "floruit_year": None},
            ])
        with open_db(db) as conn:
            run(conn)
            for r in conn.execute(
                "SELECT wikidata_id, floruit_period, method "
                "FROM individuals_floruit_period"
            ):
                log(f"  {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
