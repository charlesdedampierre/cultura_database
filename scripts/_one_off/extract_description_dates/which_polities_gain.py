"""
For the 112,661 individuals that have `dates_in_description` but no
birth/death/floruit date, estimate which Cliopatria polities would gain the
most members if we used the description-extracted dates.

Match rule (rough, first pass):
  - Convert `dates_in_description` to a candidate year (range midpoint, or
    signed BC/AD year).
  - Use `country_of_citizenship_en` as the place anchor (exact name match
    against `polities_periods_cliopatria.polity_name`).
  - Pick the polity period whose [from_year, to_year] contains the candidate
    year and whose name matches the country.
  - For each individual, collapse to a single polity_name (the matched one).
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter
from pathlib import Path

from tqdm import tqdm

DB = Path("/Users/charlesdedampierre/Desktop/Rsearch Folder/cultura_database/data/humans_clean.sqlite3")

YEAR_MARKER_RE = re.compile(r"^(\d+)\s+(BC|BCE|AC|AD|CE)$")
RANGE_RE = re.compile(r"^(\d{4})-(\d{4})$")
SINGLE_TAG_RE = re.compile(r"^(?:b|d|fl)\s+(\d{3,4})$")
CENTURY_RE = re.compile(r"^c(\d{1,2})(?:\s+(BC|BCE|AC))?$")


def token_to_year(token: str) -> int | None:
    """First token wins. Returns signed integer year or None."""
    token = token.strip()
    m = RANGE_RE.match(token)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return (a + b) // 2
    m = YEAR_MARKER_RE.match(token)
    if m:
        y, mk = int(m.group(1)), m.group(2)
        if mk in ("BC", "BCE", "AC"):
            return -y
        return y
    m = SINGLE_TAG_RE.match(token)
    if m:
        return int(m.group(1))
    m = CENTURY_RE.match(token)
    if m:
        n = int(m.group(1))
        # midpoint of an N-th century (1..N) is (N-1)*100 + 50.
        midpoint = (n - 1) * 100 + 50
        if m.group(2) in ("BC", "BCE", "AC"):
            return -midpoint
        return midpoint
    return None


def to_year(value: str) -> int | None:
    for tok in value.split("|"):
        y = token_to_year(tok)
        if y is not None:
            return y
    return None


def main() -> None:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        SELECT wikidata_id, country_of_citizenship_en, dates_in_description
        FROM individuals
        WHERE dates_in_description IS NOT NULL
          AND (birthdate    IS NULL OR birthdate    = '')
          AND (deathdate    IS NULL OR deathdate    = '')
          AND (floruit_date IS NULL OR floruit_date = '')
          AND country_of_citizenship_en IS NOT NULL
          AND country_of_citizenship_en != ''
        """
    ).fetchall()
    print(f"candidate individuals (have country + extracted date): {len(rows):,}")

    # Build polity_name -> list[(from_year, to_year)] for fast lookup.
    polity_periods: dict[str, list[tuple[int, int]]] = {}
    for pid, name, fy, ty in conn.execute(
        "SELECT polity_id, polity_name, from_year, to_year FROM polities_periods_cliopatria"
    ):
        if name is None or fy is None or ty is None:
            continue
        polity_periods.setdefault(name, []).append((int(fy), int(ty)))
    print(f"distinct polities with periods: {len(polity_periods):,}")

    # country_of_citizenship_en may be a multi-value '|'-separated string.
    # We try each token; first match wins.
    polity_hits: Counter[str] = Counter()
    matched = 0
    no_year = 0
    no_polity_name_match = 0
    no_temporal_overlap = 0

    for r in tqdm(rows, desc="matching"):
        year = to_year(r["dates_in_description"])
        if year is None:
            no_year += 1
            continue
        countries = [c.strip() for c in r["country_of_citizenship_en"].split("|") if c.strip()]
        chosen = None
        any_name_match = False
        for c in countries:
            periods = polity_periods.get(c)
            if not periods:
                continue
            any_name_match = True
            for fy, ty in periods:
                if fy <= year <= ty:
                    chosen = c
                    break
            if chosen:
                break
        if chosen:
            polity_hits[chosen] += 1
            matched += 1
        elif not any_name_match:
            no_polity_name_match += 1
        else:
            no_temporal_overlap += 1

    conn.close()

    print()
    print(f"matched              : {matched:,}")
    print(f"no candidate year    : {no_year:,}")
    print(f"country has no polity: {no_polity_name_match:,}")
    print(f"polity exists but year outside its periods: {no_temporal_overlap:,}")
    print()
    print("=== Top polities that would gain individuals (absolute) ===")
    for name, n in polity_hits.most_common(20):
        print(f"  {n:>6}  {name}")

    # Now compute % gain: gain / current size in individuals_cliopatria.
    # IMPORTANT: individuals_cliopatria.polity_name is a ';'-separated
    # multi-polity string. Split it to count true per-polity membership.
    conn2 = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    current: Counter[str] = Counter()
    seen_pairs: set[tuple[str, str]] = set()
    for wid, raw in conn2.execute(
        "SELECT wikidata_id, polity_name FROM individuals_cliopatria WHERE polity_name IS NOT NULL"
    ):
        for p in raw.split(";"):
            p = p.strip()
            if not p:
                continue
            key = (wid, p)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            current[p] += 1
    conn2.close()
    print(f"distinct polities currently populated: {len(current):,}")

    print()
    print("=== Top polities by % gain (gain / current size), min gain >= 3 ===")
    print(f"  {'gain':>6}  {'current':>8}  {'%gain':>8}  polity")
    rows = []
    for name, gain in polity_hits.items():
        if gain < 3:
            continue
        cur = current.get(name, 0)
        pct = (gain / cur * 100.0) if cur > 0 else float("inf")
        rows.append((pct, gain, cur, name))
    rows.sort(reverse=True)
    for pct, gain, cur, name in rows[:30]:
        pct_str = f"{pct:>7.2f}%" if cur > 0 else "  (new) "
        print(f"  {gain:>6}  {cur:>8}  {pct_str}  {name}")


if __name__ == "__main__":
    main()
