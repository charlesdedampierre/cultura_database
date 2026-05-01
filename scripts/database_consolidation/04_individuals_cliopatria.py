"""50 — Rebuild individuals_cliopatria with multi-polity matching.

Mirrors `enhance_db/src/bin/50_rebuild_individuals_cliopatria.rs`.

Priority order (year-aware):
  1. nationality polygon
  2. nationality URL
  3. birthplace polygon
  4. birthplace URL
  5. deathplace polygon
  6. deathplace URL
  7. fallback (no impact_year): URL only — nat -> birth -> death.

Multi-polity output: polity_id and polity_name are semicolon-joined.
Uses shapely for point-in-polygon. Geometries are GeoJSON strings.

Usage
-----
    python3 50_rebuild_individuals_cliopatria.py
    python3 50_rebuild_individuals_cliopatria.py --full
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from shapely.geometry import Point, shape
from tqdm import tqdm

from common import (
    DB_PATH,
    insert_rows,
    log,
    open_db,
    parse_run_mode,
    parse_year,
)

BATCH_SIZE = 50_000


def _load_polity_id_to_name(conn: sqlite3.Connection) -> dict[int, str]:
    return dict(conn.execute("SELECT id, name FROM polities_cliopatria").fetchall())


def _load_url_to_polities(conn: sqlite3.Connection) -> dict[str, list[tuple[str, int]]]:
    out: dict[str, list[tuple[str, int]]] = {}
    for pid, name, url in conn.execute(
        "SELECT id, name, wikipedia_url FROM polities_cliopatria "
        "WHERE wikipedia_url IS NOT NULL"
    ):
        out.setdefault(url, []).append((name, pid))
    return out


def _load_periods(
    conn: sqlite3.Connection, name_lookup: dict[int, str]
) -> list[dict]:
    periods: list[dict] = []
    for pid, pname, fy, ty, _area, geom_str in conn.execute(
        "SELECT polity_id, polity_name, from_year, to_year, area, geometry "
        "FROM cliopatria_polity_periods WHERE geometry IS NOT NULL"
    ):
        try:
            geom = shape(json.loads(geom_str))
        except Exception:
            continue
        periods.append({
            "polity_id": pid,
            "polity_name": name_lookup.get(pid, pname),
            "from_year": fy,
            "to_year": ty,
            "geom": geom,
            "bounds": geom.bounds,  # (minx, miny, maxx, maxy)
        })
    return periods


def _load_place_lookup(
    conn: sqlite3.Connection,
    sql: str,
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for wid, name_en, lon, lat, url in conn.execute(sql):
        out[wid] = {
            "name_en": name_en or "",
            "coords": (lon, lat) if (lon is not None and lat is not None) else None,
            "url": url,
        }
    return out


def _find_polities_by_polygon(
    periods: list[dict], lon: float, lat: float, year: int
) -> list[tuple[str, int]]:
    pt = Point(lon, lat)
    seen: dict[int, str] = {}
    for pp in periods:
        if year < pp["from_year"] or year > pp["to_year"]:
            continue
        minx, miny, maxx, maxy = pp["bounds"]
        if lon < minx or lon > maxx or lat < miny or lat > maxy:
            continue
        if pp["geom"].contains(pt):
            seen.setdefault(pp["polity_id"], pp["polity_name"])
    return [(name, pid) for pid, name in seen.items()]


def _find_polities_by_url(
    url_map: dict[str, list[tuple[str, int]]],
    year_ranges: dict[int, list[tuple[int, int]]],
    url: str,
    year: int,
) -> list[tuple[str, int]]:
    out = []
    for name, pid in url_map.get(url, []):
        for f, t in year_ranges.get(pid, []):
            if f <= year <= t:
                out.append((name, pid))
                break
    return out


def run(conn: sqlite3.Connection) -> int:
    log("[DB] 50: Rebuild individuals_cliopatria...")
    name_lookup = _load_polity_id_to_name(conn)
    url_to_polities = _load_url_to_polities(conn)
    periods = _load_periods(conn, name_lookup)
    log(f"[DB] {len(periods)} polity periods loaded")

    city_lookup = _load_place_lookup(
        conn,
        "SELECT id, name_en, lon, lat, en_wikipedia_url_original_country_name "
        "FROM cities",
    )
    nat_lookup = _load_place_lookup(
        conn,
        "SELECT wikidata_id, name_en, lon, lat, en_wikipedia_url FROM nationalities",
    )

    impact: dict[str, int] = {}
    for wid, ds in conn.execute(
        "SELECT wikidata_id, impact_date FROM individuals_impact_date"
    ):
        y = parse_year(ds)
        if y is not None:
            impact[wid] = y

    year_ranges: dict[int, list[tuple[int, int]]] = {}
    for pid, fy, ty in conn.execute(
        "SELECT polity_id, from_year, to_year FROM cliopatria_polity_periods"
    ):
        year_ranges.setdefault(pid, []).append((fy, ty))

    conn.execute("DROP TABLE IF EXISTS individuals_cliopatria")
    conn.execute(
        """
        CREATE TABLE individuals_cliopatria (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            polity_name TEXT,
            polity_id TEXT,
            origin TEXT,
            matched_name TEXT,
            matched_wikidata_id TEXT,
            method TEXT,
            impact_date INTEGER
        )
        """
    )

    total = conn.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]
    inserted = 0

    def _try_year_steps(wid, nationalities_ids, birth_id, death_id, year):
        # priority list of (origin, kind, place)
        if nationalities_ids:
            for nat_id in nationalities_ids.split(";"):
                nat_id = nat_id.strip()
                if not nat_id:
                    continue
                info = nat_lookup.get(nat_id)
                if not info:
                    continue
                if info["coords"]:
                    lon, lat = info["coords"]
                    pols = _find_polities_by_polygon(periods, lon, lat, year)
                    if pols:
                        return (pols, "nationality", info["name_en"], nat_id, "polygon")
            for nat_id in nationalities_ids.split(";"):
                nat_id = nat_id.strip()
                if not nat_id:
                    continue
                info = nat_lookup.get(nat_id)
                if info and info["url"]:
                    pols = _find_polities_by_url(url_to_polities, year_ranges, info["url"], year)
                    if pols:
                        return (pols, "nationality", info["name_en"], nat_id, "url")
        for cid, origin in ((birth_id, "birthplace"), (death_id, "deathplace")):
            if not cid:
                continue
            cid = cid.strip()
            if not cid:
                continue
            info = city_lookup.get(cid)
            if not info:
                continue
            if info["coords"]:
                lon, lat = info["coords"]
                pols = _find_polities_by_polygon(periods, lon, lat, year)
                if pols:
                    return (pols, origin, info["name_en"], cid, "polygon")
            if info["url"]:
                pols = _find_polities_by_url(url_to_polities, year_ranges, info["url"], year)
                if pols:
                    return (pols, origin, info["name_en"], cid, "url")
        return None

    def _try_fallback(wid, nationalities_ids, birth_id, death_id):
        if nationalities_ids:
            for nat_id in nationalities_ids.split(";"):
                nat_id = nat_id.strip()
                if not nat_id:
                    continue
                info = nat_lookup.get(nat_id)
                if info and info["url"]:
                    pols = url_to_polities.get(info["url"])
                    if pols:
                        return (list(pols), "nationality", info["name_en"], nat_id, "url_fallback")
        for cid, origin in ((birth_id, "birthplace"), (death_id, "deathplace")):
            if not cid:
                continue
            cid = cid.strip()
            if not cid:
                continue
            info = city_lookup.get(cid)
            if info and info["url"]:
                pols = url_to_polities.get(info["url"])
                if pols:
                    return (list(pols), origin, info["name_en"], cid, "url_fallback")
        return None

    cur = conn.cursor()
    cur.execute("BEGIN")
    insert_sql = (
        "INSERT OR IGNORE INTO individuals_cliopatria "
        "(wikidata_id, name_en, polity_name, polity_id, origin, "
        "matched_name, matched_wikidata_id, method, impact_date) "
        "VALUES (?,?,?,?,?,?,?,?,?)"
    )

    rows_iter = conn.execute(
        "SELECT i.wikidata_id, i.name_en, k.birthcity_id, k.deathcity_id, k.nationalities_ids "
        "FROM individuals i LEFT JOIN individuals_keys k "
        "ON i.wikidata_id = k.wikidata_id"
    )
    for wid, name_en, birth_id, death_id, nat_ids in tqdm(
        rows_iter, total=total, desc="Matching", unit="row"
    ):
        match = None
        year = impact.get(wid)
        if year is not None:
            match = _try_year_steps(wid, nat_ids, birth_id, death_id, year)
        if match is None and year is None:
            match = _try_fallback(wid, nat_ids, birth_id, death_id)
        if match is None:
            continue
        pols, origin, mname, mwid, method = match
        pnames = ";".join(p[0] for p in pols)
        pids = ";".join(str(p[1]) for p in pols)
        cur.execute(
            insert_sql,
            (wid, name_en, pnames, pids, origin, mname, mwid, method, year),
        )
        inserted += 1
        if inserted % BATCH_SIZE == 0:
            conn.commit()
            cur.execute("BEGIN")
    conn.commit()

    log(f"[DB] inserted {inserted} rows")

    for sql in (
        "CREATE INDEX IF NOT EXISTS idx_ic_polity ON individuals_cliopatria(polity_name)",
        "CREATE INDEX IF NOT EXISTS idx_ic_polity_id ON individuals_cliopatria(polity_id)",
        "CREATE INDEX IF NOT EXISTS idx_ic_origin ON individuals_cliopatria(origin)",
        "CREATE INDEX IF NOT EXISTS idx_ic_method ON individuals_cliopatria(method)",
    ):
        conn.execute(sql)
    conn.commit()

    # Update polities_cliopatria.number_individuals
    counts: dict[int, int] = {}
    for (pid_str,) in conn.execute("SELECT polity_id FROM individuals_cliopatria"):
        for p in pid_str.split(";"):
            p = p.strip()
            if p.isdigit() or (p.startswith("-") and p[1:].isdigit()):
                counts[int(p)] = counts.get(int(p), 0) + 1

    cols = {r[1] for r in conn.execute("PRAGMA table_info(polities_cliopatria)")}
    if "number_individuals" not in cols:
        conn.execute(
            "ALTER TABLE polities_cliopatria ADD COLUMN number_individuals INTEGER DEFAULT 0"
        )
    conn.execute("UPDATE polities_cliopatria SET number_individuals = 0")
    conn.executemany(
        "UPDATE polities_cliopatria SET number_individuals = ? WHERE id = ?",
        [(c, pid) for pid, c in counts.items()],
    )
    conn.commit()
    return inserted


def _sample_main() -> None:
    poly_geo = json.dumps({
        "type": "Polygon",
        "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
    })
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE polities_cliopatria (id INTEGER PRIMARY KEY, "
                "name TEXT, wikipedia_url TEXT, number_individuals INTEGER DEFAULT 0)"
            )
            insert_rows(seed, "polities_cliopatria", [
                {"id": 1, "name": "Han", "wikipedia_url": "http://han"},
            ])
            seed.execute(
                "CREATE TABLE cliopatria_polity_periods (polity_id INTEGER, "
                "polity_name TEXT, from_year INTEGER, to_year INTEGER, "
                "area REAL, geometry TEXT)"
            )
            insert_rows(seed, "cliopatria_polity_periods", [{
                "polity_id": 1, "polity_name": "Han",
                "from_year": -200, "to_year": 220,
                "area": 100.0, "geometry": poly_geo,
            }])
            seed.execute(
                "CREATE TABLE cities (id TEXT PRIMARY KEY, name_en TEXT, "
                "lon REAL, lat REAL, en_wikipedia_url_original_country_name TEXT)"
            )
            insert_rows(seed, "cities", [
                {"id": "Q1001", "name_en": "Chang'an", "lon": 5.0, "lat": 5.0,
                 "en_wikipedia_url_original_country_name": None},
            ])
            seed.execute(
                "CREATE TABLE nationalities (wikidata_id TEXT PRIMARY KEY, "
                "name_en TEXT, lon REAL, lat REAL, en_wikipedia_url TEXT)"
            )
            seed.execute(
                "CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, name_en TEXT)"
            )
            insert_rows(seed, "individuals", [
                {"wikidata_id": "Q1", "name_en": "Han Person"},
            ])
            seed.execute(
                "CREATE TABLE individuals_keys (wikidata_id TEXT PRIMARY KEY, "
                "birthcity_id TEXT, deathcity_id TEXT, nationalities_ids TEXT)"
            )
            insert_rows(seed, "individuals_keys", [
                {"wikidata_id": "Q1", "birthcity_id": "Q1001",
                 "deathcity_id": None, "nationalities_ids": None},
            ])
            seed.execute(
                "CREATE TABLE individuals_impact_date (wikidata_id TEXT, impact_date TEXT)"
            )
            insert_rows(seed, "individuals_impact_date", [
                {"wikidata_id": "Q1", "impact_date": "100"},
            ])
        with open_db(db) as conn:
            run(conn)
            for r in conn.execute(
                "SELECT wikidata_id, polity_name, polity_id, method "
                "FROM individuals_cliopatria"
            ):
                log(f"  {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
