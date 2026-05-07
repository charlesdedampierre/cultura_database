"""Estimate per-polity coverage gains from the description-extracted dates.

A "candidate" is an individual who:
  - currently has NO floruit_period (not in individuals_floruit_period.floruit_period)
  - now has a year derivable from the description (floruit_year_in_description)
  - has at least one country_of_citizenship matching a Cliopatria polity name
  - whose extracted year falls inside one of that polity's periods

We count, per polity, how many such candidates we'd add, and compare to the
polity's current member count in `individuals_cliopatria`.

Outputs a ranked table:
  - Top polities by absolute gain
  - Top polities by relative gain (gain / current_members), min current ≥ 50

Estimated runtime: ~10s on local SSD.
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path

from tqdm import tqdm

DB = Path("/Users/charlesdedampierre/Desktop/Rsearch Folder/cultura_database/data/humans_clean.sqlite3")


def main() -> None:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    # All candidate individuals: lack a floruit_period but now have a year.
    rows = conn.execute(
        """
        SELECT i.wikidata_id,
               i.country_of_citizenship_en,
               i.floruit_year_in_description AS year
        FROM individuals i
        JOIN individuals_floruit_period fp USING (wikidata_id)
        WHERE (fp.floruit_period IS NULL OR fp.floruit_period = '')
          AND i.floruit_year_in_description IS NOT NULL
          AND i.country_of_citizenship_en IS NOT NULL
          AND i.country_of_citizenship_en != ''
        """
    ).fetchall()
    print(f"candidate individuals (no floruit, have desc-year, have country): {len(rows):,}")

    # polity_name → list[(from_year, to_year)]
    polity_periods: dict[str, list[tuple[int, int]]] = {}
    for name, fy, ty in conn.execute(
        "SELECT polity_name, from_year, to_year FROM polities_periods_cliopatria"
    ):
        if name is None or fy is None or ty is None:
            continue
        polity_periods.setdefault(name, []).append((int(fy), int(ty)))
    print(f"distinct polities with periods: {len(polity_periods):,}")

    # Match each candidate to one polity.
    polity_gains: Counter[str] = Counter()
    matched = 0
    no_country_match = 0
    no_temporal_match = 0
    for r in tqdm(rows, desc="matching candidates"):
        countries = [c.strip() for c in r["country_of_citizenship_en"].split("|") if c.strip()]
        chosen: str | None = None
        any_country_in_clio = False
        for c in countries:
            periods = polity_periods.get(c)
            if not periods:
                continue
            any_country_in_clio = True
            for fy, ty in periods:
                if fy <= r["year"] <= ty:
                    chosen = c
                    break
            if chosen:
                break
        if chosen:
            polity_gains[chosen] += 1
            matched += 1
        elif not any_country_in_clio:
            no_country_match += 1
        else:
            no_temporal_match += 1

    print(f"\nmatched              : {matched:,}")
    print(f"country not a polity : {no_country_match:,}")
    print(f"year outside periods : {no_temporal_match:,}")

    # Existing polity sizes from individuals_cliopatria — split semicolon-joined names.
    current: Counter[str] = Counter()
    seen_pairs: set[tuple[str, str]] = set()
    for wid, raw in conn.execute(
        "SELECT wikidata_id, polity_name FROM individuals_cliopatria WHERE polity_name IS NOT NULL"
    ):
        for p in raw.split(";"):
            p = p.strip()
            if not p:
                continue
            if (wid, p) in seen_pairs:
                continue
            seen_pairs.add((wid, p))
            current[p] += 1
    conn.close()
    print(f"distinct polities currently populated: {len(current):,}\n")

    print("=== Top 25 polities by ABSOLUTE gain ===")
    print(f"  {'gain':>6}  {'current':>9}  {'%gain':>8}  polity")
    for name, gain in polity_gains.most_common(25):
        cur = current.get(name, 0)
        pct = (gain / cur * 100.0) if cur > 0 else float("inf")
        pct_str = f"{pct:>7.1f}%" if cur > 0 else "  (new) "
        print(f"  {gain:>6}  {cur:>9}  {pct_str}  {name}")

    print("\n=== Top 25 polities by RELATIVE gain (gain / current, current ≥ 50) ===")
    print(f"  {'gain':>6}  {'current':>9}  {'%gain':>8}  polity")
    rel = []
    for name, gain in polity_gains.items():
        cur = current.get(name, 0)
        if cur < 50:
            continue
        rel.append((gain / cur, gain, cur, name))
    rel.sort(reverse=True)
    for ratio, gain, cur, name in rel[:25]:
        print(f"  {gain:>6}  {cur:>9}  {ratio*100:>7.1f}%  {name}")

    print("\n=== New polities (no current members but gain ≥ 5) ===")
    new_only = sorted(
        ((name, g) for name, g in polity_gains.items() if current.get(name, 0) == 0 and g >= 5),
        key=lambda x: -x[1],
    )
    for name, g in new_only[:25]:
        print(f"  {g:>6}     (new)             {name}")


if __name__ == "__main__":
    main()
