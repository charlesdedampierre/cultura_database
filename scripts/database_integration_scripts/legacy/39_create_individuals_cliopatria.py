"""39 - Create individuals_cliopatria (polygon-first, URL fallback).

Mirrors `enhance_db/src/bin/39_create_individuals_cliopatria.rs`.

Priority order:
  1. Deathplace polygon  (requires impact_date)
  2. Birthplace polygon  (requires impact_date)
  3. Nationality polygon (requires impact_date)
  4. URL nationality
  5. URL deathcity
  6. URL birthcity

Polygon containment uses shapely (`shape(geojson).contains(Point(lon,lat))`)
which already handles MultiPolygon and bbox pre-filter internally.

  Inputs : individuals, nationalities, cities, individuals_impact_date,
           cliopatria.db (polities + polity_periods)
  Output : individuals_cliopatria (wikidata_id PK, name_en, polity_name,
                                    polity_id, origin, matched_name, method)
           polities_cliopatria.mixed_count column updated.

Usage
-----
    python3 39_create_individuals_cliopatria.py            # synthetic
    python3 39_create_individuals_cliopatria.py --full     # real DB
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from shapely.geometry import Point, shape
from tqdm import tqdm

from common import (
    PROJECT_ROOT,
    add_column_if_missing,
    insert_rows,
    log,
    open_db,
    parse_run_mode,
    parse_year,
)

CLIO_DB_PATH = PROJECT_ROOT / "cliopatria_data" / "processing" / "data" / "cliopatria.db"
BATCH_SIZE = 50_000


def _strip_parens(s: str) -> str:
    s = s.strip()
    if s.startswith("(") and s.endswith(")"):
        return s[1:-1]
    return s


def _load_periods(clio: sqlite3.Connection, polity_id_to_name: dict[int, str]) -> list[dict]:
    periods: list[dict] = []
    skipped = 0
    for pid, pname, from_y, to_y, geom_str in clio.execute(
        "SELECT polity_id, polity_name, from_year, to_year, geometry "
        "FROM polity_periods WHERE geometry IS NOT NULL"
    ):
        try:
            geom = shape(json.loads(geom_str))
        except Exception:
            skipped += 1
            continue
        clean_name = polity_id_to_name.get(pid, _strip_parens(pname))
        bounds = geom.bounds  # (minx, miny, maxx, maxy)
        area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
        periods.append({
            "polity_id": pid,
            "polity_name": clean_name,
            "from_year": from_y,
            "to_year": to_y,
            "area": area,
            "geom": geom,
        })
    log(f"[39] loaded {len(periods)} polity periods ({skipped} skipped)")
    return periods


def _find_polity(periods: list[dict], lon: float, lat: float, year: int):
    pt = Point(lon, lat)
    best = None
    for pp in periods:
        if year < pp["from_year"] or year > pp["to_year"]:
            continue
        if pp["geom"].contains(pt):
            if best is None or pp["area"] < best["area"]:
                best = pp
    if best is None:
        return None
    return best["polity_name"], best["polity_id"]


def run(conn: sqlite3.Connection, clio_db_path: Path | str = CLIO_DB_PATH) -> int:
    log("[DB] 39: Creating individuals_cliopatria...")

    with sqlite3.connect(str(clio_db_path)) as clio:
        polity_id_to_name = {pid: _strip_parens(n) for pid, n in clio.execute(
            "SELECT id, name FROM polities")}
        url_to_polity: dict[str, tuple[str, int]] = {}
        for pid, name, url in clio.execute(
            "SELECT id, name, wikipedia_url FROM polities WHERE wikipedia_url IS NOT NULL"
        ):
            url_to_polity.setdefault(url, (_strip_parens(name), pid))
        periods = _load_periods(clio, polity_id_to_name)

    nat_url = {n: u for n, u in conn.execute(
        "SELECT name_en, en_wikipedia_url FROM nationalities WHERE en_wikipedia_url IS NOT NULL")}
    city_url: dict[str, str] = {}
    for n, u in conn.execute(
        "SELECT name_en, en_wikipedia_url_original_country_name FROM cities "
        "WHERE en_wikipedia_url_original_country_name IS NOT NULL"
    ):
        city_url.setdefault(n, u)
    nat_loc = {n: (lo, la) for n, lo, la in conn.execute(
        "SELECT name_en, lon, lat FROM nationalities WHERE lat IS NOT NULL AND lon IS NOT NULL")}
    city_loc: dict[str, tuple[float, float]] = {}
    for n, lo, la in conn.execute(
        "SELECT name_en, lon, lat FROM cities WHERE lat IS NOT NULL AND lon IS NOT NULL"
    ):
        city_loc.setdefault(n, (lo, la))
    impact: dict[str, int] = {}
    for wid, ds in conn.execute(
        "SELECT wikidata_id, impact_date FROM individuals_impact_date"
    ):
        y = parse_year(ds)
        if y is not None:
            impact[wid] = y

    conn.execute("DROP TABLE IF EXISTS individuals_cliopatria")
    conn.execute(
        """
        CREATE TABLE individuals_cliopatria (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            polity_name TEXT,
            polity_id INTEGER,
            origin TEXT,
            matched_name TEXT,
            method TEXT
        )
        """
    )

    total = conn.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]
    cursor = conn.execute(
        "SELECT wikidata_id, name_en, nationalities_en, deathcity_en, birthcity_en "
        "FROM individuals ORDER BY rowid"
    )
    sql = (
        "INSERT OR IGNORE INTO individuals_cliopatria "
        "(wikidata_id, name_en, polity_name, polity_id, origin, matched_name, method) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)"
    )
    inserted = 0
    buf: list[tuple] = []
    for wid, name_en, nats, dc, bc in tqdm(cursor, total=total, desc="39_clio"):
        matched = None
        year = impact.get(wid)
        if year is not None:
            if dc:
                loc = city_loc.get(dc.strip())
                if loc:
                    hit = _find_polity(periods, loc[0], loc[1], year)
                    if hit:
                        matched = (hit[0], hit[1], "deathplace", dc.strip(), "polygon")
            if matched is None and bc:
                loc = city_loc.get(bc.strip())
                if loc:
                    hit = _find_polity(periods, loc[0], loc[1], year)
                    if hit:
                        matched = (hit[0], hit[1], "birthplace", bc.strip(), "polygon")
            if matched is None and nats:
                for n in nats.split("; "):
                    loc = nat_loc.get(n.strip())
                    if not loc:
                        continue
                    hit = _find_polity(periods, loc[0], loc[1], year)
                    if hit:
                        matched = (hit[0], hit[1], "nationality", n.strip(), "polygon")
                        break
        if matched is None and nats:
            for n in nats.split("; "):
                u = nat_url.get(n.strip())
                if not u:
                    continue
                hit = url_to_polity.get(u)
                if hit:
                    matched = (hit[0], hit[1], "nationality", n.strip(), "url")
                    break
        if matched is None and dc:
            u = city_url.get(dc.strip())
            if u:
                hit = url_to_polity.get(u)
                if hit:
                    matched = (hit[0], hit[1], "deathplace", dc.strip(), "url")
        if matched is None and bc:
            u = city_url.get(bc.strip())
            if u:
                hit = url_to_polity.get(u)
                if hit:
                    matched = (hit[0], hit[1], "birthplace", bc.strip(), "url")
        if matched is None:
            continue
        buf.append((wid, name_en, *matched))
        if len(buf) >= BATCH_SIZE:
            conn.executemany(sql, buf)
            conn.commit()
            inserted += len(buf)
            buf.clear()
    if buf:
        conn.executemany(sql, buf)
        conn.commit()
        inserted += len(buf)

    for ddl in (
        "CREATE INDEX IF NOT EXISTS idx_ic_polity ON individuals_cliopatria(polity_name)",
        "CREATE INDEX IF NOT EXISTS idx_ic_polity_id ON individuals_cliopatria(polity_id)",
        "CREATE INDEX IF NOT EXISTS idx_ic_origin ON individuals_cliopatria(origin)",
        "CREATE INDEX IF NOT EXISTS idx_ic_method ON individuals_cliopatria(method)",
    ):
        conn.execute(ddl)

    add_column_if_missing(conn, "polities_cliopatria", "mixed_count", "INTEGER DEFAULT 0")
    conn.execute("UPDATE polities_cliopatria SET mixed_count = 0")
    counts = {n: c for n, c in conn.execute(
        "SELECT polity_name, COUNT(*) FROM individuals_cliopatria GROUP BY polity_name")}
    conn.executemany(
        "UPDATE polities_cliopatria SET mixed_count = ? WHERE name = ?",
        [(c, n) for n, c in counts.items()],
    )
    conn.commit()
    log(f"[39] inserted {inserted}")
    return inserted


def _sample_main() -> None:
    square = {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}
    with tempfile.TemporaryDirectory() as tmp:
        clio = Path(tmp) / "clio.db"
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(clio) as c:
            c.execute(
                "CREATE TABLE polities (id INTEGER, name TEXT, wikipedia_url TEXT)"
            )
            c.execute(
                "CREATE TABLE polity_periods (polity_id INTEGER, polity_name TEXT, "
                "from_year INTEGER, to_year INTEGER, geometry TEXT)"
            )
            insert_rows(c, "polities", [
                {"id": 1, "name": "Squareland", "wikipedia_url": "https://example.com/sq"},
            ])
            insert_rows(c, "polity_periods", [
                {"polity_id": 1, "polity_name": "Squareland", "from_year": 1000,
                 "to_year": 2000, "geometry": json.dumps(square)},
            ])
        with sqlite3.connect(db) as seed:
            seed.executescript(
                """
                CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, name_en TEXT,
                    nationalities_en TEXT, deathcity_en TEXT, birthcity_en TEXT);
                CREATE TABLE nationalities (name_en TEXT, en_wikipedia_url TEXT,
                    lon REAL, lat REAL);
                CREATE TABLE cities (name_en TEXT, en_wikipedia_url_original_country_name TEXT,
                    lon REAL, lat REAL);
                CREATE TABLE individuals_impact_date (wikidata_id TEXT, impact_date TEXT);
                CREATE TABLE polities_cliopatria (id INTEGER PRIMARY KEY, name TEXT);
                """
            )
            insert_rows(seed, "individuals", [
                {"wikidata_id": "Q1", "name_en": "Inside", "nationalities_en": None,
                 "deathcity_en": "InCity", "birthcity_en": None},
                {"wikidata_id": "Q2", "name_en": "Outside", "nationalities_en": None,
                 "deathcity_en": "FarCity", "birthcity_en": None},
            ])
            insert_rows(seed, "cities", [
                {"name_en": "InCity", "en_wikipedia_url_original_country_name": None, "lon": 5.0, "lat": 5.0},
                {"name_en": "FarCity", "en_wikipedia_url_original_country_name": None, "lon": 100.0, "lat": 100.0},
            ])
            insert_rows(seed, "individuals_impact_date", [
                {"wikidata_id": "Q1", "impact_date": "1500-01-01"},
                {"wikidata_id": "Q2", "impact_date": "1500-01-01"},
            ])
            insert_rows(seed, "polities_cliopatria", [{"id": 1, "name": "Squareland"}])

        with open_db(db) as conn:
            n = run(conn, clio_db_path=clio)
            rows = conn.execute("SELECT * FROM individuals_cliopatria").fetchall()
        log(f"[sample] {n}: {rows}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
