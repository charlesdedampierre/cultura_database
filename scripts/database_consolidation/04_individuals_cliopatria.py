"""50 — Rebuild individuals_cliopatria with multi-polity matching.

Mirrors `enhance_db/src/bin/50_rebuild_individuals_cliopatria.rs`.

Priority order (range-aware):
  1. country-of-citizenship polygon  (method=merge_with_polygon)
  2. country-of-citizenship URL      (method=merge_with_url)
  3. birthplace polygon              (method=merge_with_polygon)
  4. birthplace URL                  (method=merge_with_url)
  5. deathplace polygon              (method=merge_with_polygon)
  6. deathplace URL                  (method=merge_with_url)
  7. fallback (no floruit_period): URL only — coc -> birth -> death
                                    (method=merge_with_url).

Multi-polity output: polity_id and polity_name are semicolon-joined.
Uses shapely for point-in-polygon. Geometries are GeoJSON strings.

Performance shape (2026-05): we resolve the *location* layer once
(every distinct country-of-citizenship QID, every distinct place QID)
into a list of `(polity_id, polity_name, from_year, to_year)`
candidates by point-in-polygon and by URL. The 13M individuals are
then matched by joining their `floruit_period_start..floruit_period_end`
range with each candidate's [from_year, to_year] — pure year filter,
no geometry per row. This is orders of magnitude faster than running
the polygon test once per individual.

Usage
-----
    python3 04_individuals_cliopatria.py
    python3 04_individuals_cliopatria.py --full
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import shapely
from shapely.geometry import Point, shape
from shapely.strtree import STRtree
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


def _load_periods(conn: sqlite3.Connection, name_lookup: dict[int, str]) -> list[dict]:
    periods: list[dict] = []
    for pid, pname, fy, ty, _area, geom_str in conn.execute(
        "SELECT polity_id, polity_name, from_year, to_year, area, geometry "
        "FROM polities_periods_cliopatria WHERE geometry IS NOT NULL"
    ):
        try:
            geom = shape(json.loads(geom_str))
        except Exception:
            continue
        periods.append(
            {
                "polity_id": pid,
                "polity_name": name_lookup.get(pid, pname),
                "from_year": fy,
                "to_year": ty,
                "geom": geom,
                "bounds": geom.bounds,  # (minx, miny, maxx, maxy)
            }
        )
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


def _build_polygon_index(
    periods: list[dict],
    lookup: dict[str, dict],
    desc: str,
    tree: STRtree | None = None,
) -> dict[str, list[tuple[int, str, int, int]]]:
    """For every QID in `lookup` whose record has coords, return the list
    of `(polity_id, polity_name, from_year, to_year)` polity-periods
    whose polygon contains that point.

    Uses Shapely 2.x's batched STRtree predicate query — `tree.query(
    points, predicate='contains')` does the bbox prefilter and the
    actual point-in-polygon test fully inside C in one call, so 300 K
    points × 13.7 K polygons no longer round-trip through Python.
    """
    if not periods:
        return {}
    if tree is None:
        tree = STRtree([pp["geom"] for pp in periods])

    keys: list[str] = []
    xs: list[float] = []
    ys: list[float] = []
    for k, info in lookup.items():
        if info["coords"]:
            lon, lat = info["coords"]
            keys.append(k)
            xs.append(lon)
            ys.append(lat)

    if not keys:
        return {}

    log(f"[DB] {desc}: {len(keys)} points -> "
        f"batched STRtree contains() against {len(periods)} periods")
    points = shapely.points(xs, ys)
    # Shape (2, M):
    #   pairs[0] = INPUT (point) indices,
    #   pairs[1] = TREE  (polity-period) indices.
    # Shapely's STRtree applies the predicate as
    # `input.predicate(tree_geom)`, so to get "polygon contains point"
    # we need `predicate='within'` (point within polygon), which mirrors
    # the original `polygon.contains(point)` semantics.
    pairs = tree.query(points, predicate="within")

    out: dict[str, list[tuple[int, str, int, int]]] = {}
    for point_idx, period_idx in zip(pairs[0].tolist(), pairs[1].tolist()):
        pp = periods[period_idx]
        out.setdefault(keys[point_idx], []).append(
            (pp["polity_id"], pp["polity_name"],
             pp["from_year"], pp["to_year"])
        )
    log(f"[DB] {desc}: {len(out)} points have at least one polity match "
        f"(total {sum(len(v) for v in out.values())} hits)")
    return out


def _build_url_index(
    url_to_polities: dict[str, list[tuple[str, int]]],
    year_ranges: dict[int, list[tuple[int, int]]],
) -> dict[str, list[tuple[int, str, int, int]]]:
    """url -> list of `(polity_id, polity_name, from_year, to_year)` for
    every period of every polity whose Wikipedia URL matches. The year
    filter happens later, per individual, against this list."""
    out: dict[str, list[tuple[int, str, int, int]]] = {}
    for url, polities in url_to_polities.items():
        rows: list[tuple[int, str, int, int]] = []
        for pname, pid in polities:
            for fy, ty in year_ranges.get(pid, []):
                rows.append((pid, pname, fy, ty))
        if rows:
            out[url] = rows
    return out


def _filter_overlap(
    candidates: list[tuple[int, str, int, int]] | None,
    start: int,
    end: int,
) -> list[tuple[str, int]]:
    """Return [(polity_name, polity_id), ...] for candidates whose
    [from_year, to_year] overlaps the person's floruit-period
    [start, end]. Dedupes on polity_id (first period name wins)."""
    if not candidates:
        return []
    seen: dict[int, str] = {}
    for pid, pname, fy, ty in candidates:
        if ty < start or fy > end:
            continue
        seen.setdefault(pid, pname)
    return [(name, pid) for pid, name in seen.items()]


def run(conn: sqlite3.Connection) -> int:
    log("[DB] 50: Rebuild individuals_cliopatria...")
    name_lookup = _load_polity_id_to_name(conn)
    url_to_polities = _load_url_to_polities(conn)
    periods = _load_periods(conn, name_lookup)
    log(f"[DB] {len(periods)} polity periods loaded")

    # The legacy `places` schema (was `cities`) keeps the wiki URL under
    # `en_wikipedia_url_original_country_name`; V2 builds rename it to
    # `en_wikipedia_url`. Pick whichever column exists.
    place_cols = {
        r[1] for r in conn.execute("PRAGMA table_info(places)").fetchall()
    }
    place_url_col = (
        "en_wikipedia_url" if "en_wikipedia_url" in place_cols
        else "en_wikipedia_url_original_country_name"
    )
    place_lookup = _load_place_lookup(
        conn,
        f"SELECT id, name_en, lon, lat, {place_url_col} FROM places",
    )
    coc_lookup = _load_place_lookup(
        conn,
        "SELECT wikidata_id, name_en, lon, lat, en_wikipedia_url "
        "FROM country_of_citizenship",
    )

    # Per-person floruit *range* (start, end). Falls back to (floruit_year,
    # floruit_year) when only the legacy single-year column is populated.
    floruit_range: dict[str, tuple[int, int]] = {}
    for wid, fs, fe, fy in conn.execute(
        "SELECT wikidata_id, floruit_period_start, floruit_period_end, "
        "       floruit_year "
        "FROM individuals_floruit_period"
    ):
        if fs is not None and fe is not None:
            floruit_range[wid] = (fs, fe)
        elif fy is not None:
            floruit_range[wid] = (fy, fy)

    year_ranges: dict[int, list[tuple[int, int]]] = {}
    for pid, fy, ty in conn.execute(
        "SELECT polity_id, from_year, to_year FROM polities_periods_cliopatria"
    ):
        year_ranges.setdefault(pid, []).append((fy, ty))

    # ---- Precompute the LOCATION layer once (this is the big speed-up) ----
    # Build the STRtree once and share between coc + place batches.
    tree = STRtree([pp["geom"] for pp in periods])
    coc_polygon_index = _build_polygon_index(
        periods, coc_lookup, "coc polygons", tree=tree
    )
    place_polygon_index = _build_polygon_index(
        periods, place_lookup, "place polygons", tree=tree
    )
    url_polity_index = _build_url_index(url_to_polities, year_ranges)
    log(f"[DB] location index built: {len(coc_polygon_index)} coc polygons, "
        f"{len(place_polygon_index)} place polygons, "
        f"{len(url_polity_index)} URL entries")

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
            floruit_year INTEGER,
            floruit_period_start INTEGER,
            floruit_period_end INTEGER
        )
        """
    )

    total = conn.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]
    inserted = 0

    def _try_year_steps(wid, coc_ids, birth_id, death_id, fstart, fend):
        # All matching is now a year-range filter against precomputed
        # location -> polity-period candidate lists; no shapely calls
        # per individual.
        if coc_ids:
            for coc_id in coc_ids.split(";"):
                coc_id = coc_id.strip()
                if not coc_id:
                    continue
                info = coc_lookup.get(coc_id)
                if not info:
                    continue
                pols = _filter_overlap(
                    coc_polygon_index.get(coc_id), fstart, fend
                )
                if pols:
                    return (pols, "country_of_citizenship",
                            info["name_en"], coc_id, "merge_with_polygon")
            for coc_id in coc_ids.split(";"):
                coc_id = coc_id.strip()
                if not coc_id:
                    continue
                info = coc_lookup.get(coc_id)
                if info and info["url"]:
                    pols = _filter_overlap(
                        url_polity_index.get(info["url"]), fstart, fend
                    )
                    if pols:
                        return (pols, "country_of_citizenship",
                                info["name_en"], coc_id, "merge_with_url")
        for cid, origin in ((birth_id, "birthplace"), (death_id, "deathplace")):
            if not cid:
                continue
            cid = cid.strip()
            if not cid:
                continue
            info = place_lookup.get(cid)
            if not info:
                continue
            pols = _filter_overlap(
                place_polygon_index.get(cid), fstart, fend
            )
            if pols:
                return (pols, origin, info["name_en"], cid, "merge_with_polygon")
            if info["url"]:
                pols = _filter_overlap(
                    url_polity_index.get(info["url"]), fstart, fend
                )
                if pols:
                    return (pols, origin, info["name_en"], cid, "merge_with_url")
        return None

    def _try_fallback(wid, coc_ids, birth_id, death_id):
        if coc_ids:
            for coc_id in coc_ids.split(";"):
                coc_id = coc_id.strip()
                if not coc_id:
                    continue
                info = coc_lookup.get(coc_id)
                if info and info["url"]:
                    pols = url_to_polities.get(info["url"])
                    if pols:
                        return (
                            list(pols),
                            "country_of_citizenship",
                            info["name_en"],
                            coc_id,
                            "merge_with_url",
                        )
        for cid, origin in ((birth_id, "birthplace"), (death_id, "deathplace")):
            if not cid:
                continue
            cid = cid.strip()
            if not cid:
                continue
            info = place_lookup.get(cid)
            if info and info["url"]:
                pols = url_to_polities.get(info["url"])
                if pols:
                    return (list(pols), origin, info["name_en"], cid, "merge_with_url")
        return None

    cur = conn.cursor()
    cur.execute("BEGIN")
    insert_sql = (
        "INSERT OR IGNORE INTO individuals_cliopatria "
        "(wikidata_id, name_en, polity_name, polity_id, origin, "
        "matched_name, matched_wikidata_id, method, floruit_year, "
        "floruit_period_start, floruit_period_end) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)"
    )

    # In V2 builds the IDs (birth/death place QIDs, country-of-citizenship
    # QIDs) live on the `individuals` table directly; the legacy
    # humans_clean.sqlite3 keeps them in a side `individuals_keys` table.
    # Detect which is present so this script works for both.
    has_keys = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='individuals_keys'"
    ).fetchone() is not None
    indiv_cols = {r[1] for r in conn.execute("PRAGMA table_info(individuals)").fetchall()}
    has_inline_ids = {
        "birthcity_id", "deathcity_id", "country_of_citizenship_ids"
    }.issubset(indiv_cols)

    if has_inline_ids:
        rows_iter = conn.execute(
            "SELECT wikidata_id, name_en, birthcity_id, deathcity_id, "
            "       country_of_citizenship_ids FROM individuals"
        )
    elif has_keys:
        rows_iter = conn.execute(
            "SELECT i.wikidata_id, i.name_en, k.birthcity_id, k.deathcity_id, "
            "       k.country_of_citizenship_ids "
            "FROM individuals i LEFT JOIN individuals_keys k "
            "ON i.wikidata_id = k.wikidata_id"
        )
    else:
        raise RuntimeError(
            "individuals table has no birthcity_id/deathcity_id columns and "
            "no individuals_keys side-table is present — cannot match polities."
        )
    for wid, name_en, birth_id, death_id, coc_ids in tqdm(
        rows_iter, total=total, desc="Matching", unit="row"
    ):
        match = None
        rng = floruit_range.get(wid)
        if rng is not None:
            fstart, fend = rng
            match = _try_year_steps(wid, coc_ids, birth_id, death_id, fstart, fend)
        else:
            fstart = fend = None
        if match is None and rng is None:
            match = _try_fallback(wid, coc_ids, birth_id, death_id)
        if match is None:
            continue
        pols, origin, mname, mwid, method = match
        pnames = ";".join(p[0] for p in pols)
        pids = ";".join(str(p[1]) for p in pols)
        # Representative year: midpoint of the floruit range when known.
        rep_year = None
        if fstart is not None and fend is not None:
            rep_year = (fstart + fend) // 2
        cur.execute(
            insert_sql,
            (wid, name_en, pnames, pids, origin, mname, mwid, method,
             rep_year, fstart, fend),
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
    poly_geo = json.dumps(
        {
            "type": "Polygon",
            "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
        }
    )
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE polities_cliopatria (id INTEGER PRIMARY KEY, "
                "name TEXT, wikipedia_url TEXT, number_individuals INTEGER DEFAULT 0)"
            )
            insert_rows(
                seed,
                "polities_cliopatria",
                [
                    {"id": 1, "name": "Han", "wikipedia_url": "http://han"},
                ],
            )
            seed.execute(
                "CREATE TABLE polities_periods_cliopatria (polity_id INTEGER, "
                "polity_name TEXT, from_year INTEGER, to_year INTEGER, "
                "area REAL, geometry TEXT)"
            )
            insert_rows(
                seed,
                "polities_periods_cliopatria",
                [
                    {
                        "polity_id": 1,
                        "polity_name": "Han",
                        "from_year": -200,
                        "to_year": 220,
                        "area": 100.0,
                        "geometry": poly_geo,
                    }
                ],
            )
            seed.execute(
                "CREATE TABLE places (id TEXT PRIMARY KEY, name_en TEXT, "
                "lon REAL, lat REAL, en_wikipedia_url TEXT)"
            )
            insert_rows(
                seed,
                "places",
                [
                    {
                        "id": "Q1001",
                        "name_en": "Chang'an",
                        "lon": 5.0,
                        "lat": 5.0,
                        "en_wikipedia_url": None,
                    },
                ],
            )
            seed.execute(
                "CREATE TABLE country_of_citizenship (wikidata_id TEXT PRIMARY KEY, "
                "name_en TEXT, lon REAL, lat REAL, en_wikipedia_url TEXT)"
            )
            seed.execute(
                "CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, name_en TEXT)"
            )
            insert_rows(
                seed,
                "individuals",
                [
                    {"wikidata_id": "Q1", "name_en": "Han Person"},
                ],
            )
            seed.execute(
                "CREATE TABLE individuals_keys (wikidata_id TEXT PRIMARY KEY, "
                "birthcity_id TEXT, deathcity_id TEXT, country_of_citizenship_ids TEXT)"
            )
            insert_rows(
                seed,
                "individuals_keys",
                [
                    {
                        "wikidata_id": "Q1",
                        "birthcity_id": "Q1001",
                        "deathcity_id": None,
                        "country_of_citizenship_ids": None,
                    },
                ],
            )
            seed.execute(
                "CREATE TABLE individuals_floruit_period "
                "(wikidata_id TEXT, floruit_year INTEGER, "
                "floruit_period_start INTEGER, floruit_period_end INTEGER)"
            )
            insert_rows(
                seed,
                "individuals_floruit_period",
                [
                    {"wikidata_id": "Q1", "floruit_year": 100,
                     "floruit_period_start": 100, "floruit_period_end": 100},
                ],
            )
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
