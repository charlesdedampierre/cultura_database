"""56 — Rebuild individuals_regions using individuals_countries.impact_year.

Mirrors `enhance_db/src/bin/56_rebuild_individuals_regions.rs`.

Same as step 52 except impact_year is read straight from
individuals_countries (populated by step 55).

Usage
-----
    python3 56_rebuild_individuals_regions.py
    python3 56_rebuild_individuals_regions.py --full
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from tqdm import tqdm

from common import insert_rows, log, open_db, parse_run_mode


def run(conn: sqlite3.Connection) -> int:
    log("[DB] 56: Rebuild individuals_regions...")
    region_lookup: dict[str, list[dict]] = {}
    for mr, r, iso, sy, ey in conn.execute(
        "SELECT macro_region, region, iso_a3, start_year, end_year FROM regions"
    ):
        region_lookup.setdefault(iso, []).append({
            "macro_region": mr, "region": r,
            "start_year": sy, "end_year": ey,
        })

    conn.execute("DROP TABLE IF EXISTS individuals_regions")
    conn.execute(
        """
        CREATE TABLE individuals_regions (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            iso_country_name TEXT,
            iso_a3_code TEXT,
            origins TEXT,
            region TEXT,
            macro_region TEXT,
            impact_year INTEGER
        )
        """
    )
    total = conn.execute("SELECT COUNT(*) FROM individuals_countries").fetchone()[0]
    inserted = 0
    cur = conn.cursor()
    cur.execute("BEGIN")
    for wid, name_en, country, iso, origins, year in tqdm(
        conn.execute(
            "SELECT wikidata_id, name_en, iso_country_name, iso_a3_code, "
            "origins, impact_year FROM individuals_countries"
        ),
        total=total, desc="56", unit="row",
    ):
        if year is None:
            continue
        entries = region_lookup.get(iso)
        if not entries:
            continue
        regions, macros = [], []
        for e in entries:
            in_range = year >= e["start_year"] and (
                e["end_year"] is None or year <= e["end_year"]
            )
            if in_range:
                if e["region"] not in regions:
                    regions.append(e["region"])
                if e["macro_region"] not in macros:
                    macros.append(e["macro_region"])
        if not regions:
            continue
        cur.execute(
            "INSERT OR IGNORE INTO individuals_regions "
            "(wikidata_id, name_en, iso_country_name, iso_a3_code, origins, "
            "region, macro_region, impact_year) VALUES (?,?,?,?,?,?,?,?)",
            (wid, name_en, country, iso, origins,
             "; ".join(regions), "; ".join(macros), year),
        )
        inserted += 1
        if inserted % 50_000 == 0:
            conn.commit()
            cur.execute("BEGIN")
    conn.commit()
    log(f"[DB] inserted {inserted}")
    return inserted


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE regions (macro_region TEXT, region TEXT, "
                "iso_a3 TEXT, start_year INTEGER, end_year INTEGER)"
            )
            insert_rows(seed, "regions", [
                {"macro_region": "Europe", "region": "Western Europe",
                 "iso_a3": "FRA", "start_year": 1500, "end_year": None},
            ])
            seed.execute(
                "CREATE TABLE individuals_countries (wikidata_id TEXT PRIMARY KEY, "
                "name_en TEXT, iso_country_name TEXT, iso_a3_code TEXT, "
                "origins TEXT, impact_year INTEGER)"
            )
            insert_rows(seed, "individuals_countries", [
                {"wikidata_id": "Q1", "name_en": "Alice",
                 "iso_country_name": "France", "iso_a3_code": "FRA",
                 "origins": "nationality", "impact_year": 1700},
            ])
        with open_db(db) as conn:
            run(conn)
            for r in conn.execute("SELECT * FROM individuals_regions"):
                log(f"  {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
