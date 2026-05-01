"""42 - Recreate individuals_cliopatria using wikidata_id-keyed lookups.

Mirrors `enhance_db/src/bin/42_recreate_individuals_cliopatria.rs`.

Same priority chain as 39 but joins individuals with individuals_keys
to look up cities and nationalities by wikidata_id (avoids name
collisions like Florence-IT vs Florence-USA).

Adds two columns vs 39: matched_wikidata_id, impact_date.
URL fallback also requires the impact_date to fall in one of the
polity's periods (uses cliopatria_polity_periods).

  Inputs : individuals, individuals_keys, individuals_impact_date,
           cities, nationalities, polities_cliopatria,
           cliopatria_polity_periods
  Output : individuals_cliopatria (wikidata_id PK, name_en, polity_name,
           polity_id, origin, matched_name, matched_wikidata_id, method,
           impact_date) + 5 indexes; polities_cliopatria.mixed_count.

Usage
-----
    python3 42_recreate_individuals_cliopatria.py            # synthetic
    python3 42_recreate_individuals_cliopatria.py --full     # real DB
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from shapely.geometry import Point, shape
from tqdm import tqdm

from common import (
    add_column_if_missing,
    insert_rows,
    log,
    open_db,
    parse_run_mode,
    parse_year,
)

BATCH_SIZE = 50_000


def _load_periods(conn: sqlite3.Connection, polity_id_to_name: dict[int, str]) -> list[dict]:
    periods: list[dict] = []
    skipped = 0
    for pid, pname, from_y, to_y, db_area, geom_str in conn.execute(
        "SELECT polity_id, polity_name, from_year, to_year, area, geometry "
        "FROM cliopatria_polity_periods WHERE geometry IS NOT NULL"
    ):
        try:
            geom = shape(json.loads(geom_str))
        except Exception:
            skipped += 1
            continue
        bounds = geom.bounds
        area = db_area if db_area is not None else \
            (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
        clean = polity_id_to_name.get(pid, pname)
        periods.append({
            "polity_id": pid, "polity_name": clean,
            "from_year": from_y, "to_year": to_y,
            "area": area, "geom": geom,
        })
    log(f"[42] loaded {len(periods)} periods ({skipped} skipped)")
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


def run(conn: sqlite3.Connection) -> int:
    log("[DB] 42: Recreating individuals_cliopatria...")

    polity_id_to_name = {pid: n for pid, n in conn.execute(
        "SELECT id, name FROM polities_cliopatria")}
    url_to_polity: dict[str, tuple[str, int]] = {}
    for pid, name, url in conn.execute(
        "SELECT id, name, wikipedia_url FROM polities_cliopatria WHERE wikipedia_url IS NOT NULL"
    ):
        url_to_polity.setdefault(url, (name, pid))

    periods = _load_periods(conn, polity_id_to_name)

    polity_id_to_years: dict[int, list[tuple[int, int]]] = {}
    for pid, fy, ty in conn.execute(
        "SELECT polity_id, from_year, to_year FROM cliopatria_polity_periods"
    ):
        polity_id_to_years.setdefault(pid, []).append((fy, ty))

    city_lookup: dict[str, dict] = {}
    for cid, name_en, lon, lat, url in conn.execute(
        "SELECT id, name_en, lon, lat, en_wikipedia_url_original_country_name FROM cities"
    ):
        city_lookup[cid] = {
            "name_en": name_en or "",
            "coords": (lon, lat) if lon is not None and lat is not None else None,
            "url": url,
        }
    nat_lookup: dict[str, dict] = {}
    for wid, name_en, lon, lat, url in conn.execute(
        "SELECT wikidata_id, name_en, lon, lat, en_wikipedia_url FROM nationalities"
    ):
        nat_lookup[wid] = {
            "name_en": name_en or "",
            "coords": (lon, lat) if lon is not None and lat is not None else None,
            "url": url,
        }

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
            matched_wikidata_id TEXT,
            method TEXT,
            impact_date INTEGER
        )
        """
    )
    total = conn.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]
    cursor = conn.execute(
        "SELECT i.wikidata_id, i.name_en, k.birthcity_id, k.deathcity_id, k.nationalities_ids "
        "FROM individuals i LEFT JOIN individuals_keys k ON i.wikidata_id = k.wikidata_id "
        "ORDER BY i.rowid"
    )
    sql = (
        "INSERT OR IGNORE INTO individuals_cliopatria "
        "(wikidata_id, name_en, polity_name, polity_id, origin, matched_name, "
        "matched_wikidata_id, method, impact_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    inserted = 0
    buf: list[tuple] = []

    def _url_match(year: int, info: dict, origin: str, matched_id: str):
        url = info.get("url")
        if not url:
            return None
        hit = url_to_polity.get(url)
        if not hit:
            return None
        polity_name, polity_id = hit
        years = polity_id_to_years.get(polity_id, [])
        if not any(fy <= year <= ty for fy, ty in years):
            return None
        return (polity_name, polity_id, origin, info["name_en"], matched_id, "url", year)

    for wid, name_en, bc_id, dc_id, nat_ids in tqdm(cursor, total=total, desc="42_clio"):
        matched = None
        year = impact.get(wid)
        if year is not None:
            if dc_id and dc_id.strip():
                info = city_lookup.get(dc_id.strip())
                if info and info["coords"]:
                    hit = _find_polity(periods, *info["coords"], year)
                    if hit:
                        matched = (hit[0], hit[1], "deathplace", info["name_en"],
                                   dc_id.strip(), "polygon", year)
            if matched is None and bc_id and bc_id.strip():
                info = city_lookup.get(bc_id.strip())
                if info and info["coords"]:
                    hit = _find_polity(periods, *info["coords"], year)
                    if hit:
                        matched = (hit[0], hit[1], "birthplace", info["name_en"],
                                   bc_id.strip(), "polygon", year)
            if matched is None and nat_ids:
                for nid in nat_ids.split(";"):
                    nid = nid.strip()
                    if not nid:
                        continue
                    info = nat_lookup.get(nid)
                    if info and info["coords"]:
                        hit = _find_polity(periods, *info["coords"], year)
                        if hit:
                            matched = (hit[0], hit[1], "nationality",
                                       info["name_en"], nid, "polygon", year)
                            break
            if matched is None and nat_ids:
                for nid in nat_ids.split(";"):
                    nid = nid.strip()
                    info = nat_lookup.get(nid) if nid else None
                    if info:
                        m = _url_match(year, info, "nationality", nid)
                        if m:
                            matched = m
                            break
            if matched is None and dc_id and dc_id.strip():
                info = city_lookup.get(dc_id.strip())
                if info:
                    m = _url_match(year, info, "deathplace", dc_id.strip())
                    if m:
                        matched = m
            if matched is None and bc_id and bc_id.strip():
                info = city_lookup.get(bc_id.strip())
                if info:
                    m = _url_match(year, info, "birthplace", bc_id.strip())
                    if m:
                        matched = m
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
        "CREATE INDEX IF NOT EXISTS idx_ic_matched_wid ON individuals_cliopatria(matched_wikidata_id)",
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
    log(f"[42] inserted {inserted}")
    return inserted


def _sample_main() -> None:
    square = {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.executescript(
                """
                CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, name_en TEXT);
                CREATE TABLE individuals_keys (wikidata_id TEXT PRIMARY KEY,
                    birthcity_id TEXT, deathcity_id TEXT, nationalities_ids TEXT);
                CREATE TABLE cities (id TEXT PRIMARY KEY, name_en TEXT, lon REAL, lat REAL,
                    en_wikipedia_url_original_country_name TEXT);
                CREATE TABLE nationalities (wikidata_id TEXT PRIMARY KEY, name_en TEXT,
                    lon REAL, lat REAL, en_wikipedia_url TEXT);
                CREATE TABLE individuals_impact_date (wikidata_id TEXT, impact_date TEXT);
                CREATE TABLE polities_cliopatria (id INTEGER PRIMARY KEY, name TEXT,
                    wikipedia_url TEXT);
                CREATE TABLE cliopatria_polity_periods (polity_id INTEGER, polity_name TEXT,
                    from_year INTEGER, to_year INTEGER, area REAL, geometry TEXT);
                """
            )
            insert_rows(seed, "individuals", [
                {"wikidata_id": "Q1", "name_en": "Inside"},
                {"wikidata_id": "Q2", "name_en": "Outside"},
            ])
            insert_rows(seed, "individuals_keys", [
                {"wikidata_id": "Q1", "birthcity_id": None, "deathcity_id": "QC1",
                 "nationalities_ids": None},
                {"wikidata_id": "Q2", "birthcity_id": None, "deathcity_id": "QC2",
                 "nationalities_ids": None},
            ])
            insert_rows(seed, "cities", [
                {"id": "QC1", "name_en": "InCity", "lon": 5.0, "lat": 5.0,
                 "en_wikipedia_url_original_country_name": None},
                {"id": "QC2", "name_en": "FarCity", "lon": 100.0, "lat": 100.0,
                 "en_wikipedia_url_original_country_name": None},
            ])
            insert_rows(seed, "individuals_impact_date", [
                {"wikidata_id": "Q1", "impact_date": "1500"},
                {"wikidata_id": "Q2", "impact_date": "1500"},
            ])
            insert_rows(seed, "polities_cliopatria", [
                {"id": 1, "name": "Squareland", "wikipedia_url": None},
            ])
            insert_rows(seed, "cliopatria_polity_periods", [
                {"polity_id": 1, "polity_name": "Squareland", "from_year": 1000,
                 "to_year": 2000, "area": 100.0, "geometry": json.dumps(square)},
            ])
        with open_db(db) as conn:
            n = run(conn)
            rows = conn.execute(
                "SELECT wikidata_id, polity_name, method, impact_date FROM individuals_cliopatria"
            ).fetchall()
        log(f"[sample] {n} matched: {rows}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
