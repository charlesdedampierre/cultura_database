"""Benchmark scripts/database_consolidation/04_individuals_cliopatria.py.

Same logic as the original (load polity periods, build STRtree, precompute
location -> polity-period candidates, then per-individual year-range filter
in priority order). Difference: no SQLite write — collect rows in memory
and dump to CSV. Timings reported per phase.

Usage:
  python benchmarks/bench_polity_assignment.py [--db PATH] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import polars as pl
import shapely
from shapely.geometry import shape
from shapely.strtree import STRtree
from tqdm import tqdm

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO / "data" / "humans_clean.sqlite3"
OUT_DIR = REPO / "temp_files"


# --- helpers (verbatim from 04_individuals_cliopatria.py) -------------------
def _load_polity_id_to_name(conn):
    return dict(conn.execute("SELECT id, name FROM polities_cliopatria").fetchall())


def _load_url_to_polities(conn):
    out = {}
    for pid, name, url in conn.execute(
        "SELECT id, name, wikipedia_url FROM polities_cliopatria "
        "WHERE wikipedia_url IS NOT NULL"
    ):
        out.setdefault(url, []).append((name, pid))
    return out


def _load_periods(conn, name_lookup):
    periods = []
    for pid, pname, fy, ty, _area, geom_str in conn.execute(
        "SELECT polity_id, polity_name, from_year, to_year, area, geometry "
        "FROM polities_periods_cliopatria WHERE geometry IS NOT NULL"
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
        })
    return periods


def _load_place_lookup(conn, sql):
    out = {}
    for wid, name_en, lon, lat, url in conn.execute(sql):
        out[wid] = {
            "name_en": name_en or "",
            "coords": (lon, lat) if (lon is not None and lat is not None) else None,
            "url": url,
        }
    return out


def _build_polygon_index(periods, lookup, desc, tree=None):
    if not periods:
        return {}
    if tree is None:
        tree = STRtree([pp["geom"] for pp in periods])
    keys, xs, ys = [], [], []
    for k, info in lookup.items():
        if info["coords"]:
            lon, lat = info["coords"]
            keys.append(k); xs.append(lon); ys.append(lat)
    if not keys:
        return {}
    print(f"  [{desc}] {len(keys):,} points -> STRtree contains() vs {len(periods):,} periods")
    points = shapely.points(xs, ys)
    pairs = tree.query(points, predicate="within")
    out = {}
    for point_idx, period_idx in zip(pairs[0].tolist(), pairs[1].tolist()):
        pp = periods[period_idx]
        out.setdefault(keys[point_idx], []).append(
            (pp["polity_id"], pp["polity_name"], pp["from_year"], pp["to_year"])
        )
    print(f"  [{desc}] {len(out):,} points matched ({sum(len(v) for v in out.values()):,} hits)")
    return out


def _build_url_index(url_to_polities, year_ranges):
    out = {}
    for url, polities in url_to_polities.items():
        rows = []
        for pname, pid in polities:
            for fy, ty in year_ranges.get(pid, []):
                rows.append((pid, pname, fy, ty))
        if rows:
            out[url] = rows
    return out


def _filter_overlap(candidates, start, end):
    if not candidates:
        return []
    seen = {}
    for pid, pname, fy, ty in candidates:
        if ty < start or fy > end:
            continue
        seen.setdefault(pid, pname)
    return [(name, pid) for pid, name in seen.items()]


# --- main pipeline ----------------------------------------------------------
def run(db_path: Path, out_path: Path):
    timings = {}
    t_total = time.perf_counter()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"db: {db_path}\nout: {out_path}\n")
    conn = sqlite3.connect(str(db_path))

    # 1. Load reference layers
    t = time.perf_counter()
    name_lookup = _load_polity_id_to_name(conn)
    url_to_polities = _load_url_to_polities(conn)
    periods = _load_periods(conn, name_lookup)
    print(f"  polity periods loaded: {len(periods):,}")

    place_cols = {r[1] for r in conn.execute("PRAGMA table_info(places)").fetchall()}
    place_url_col = "en_wikipedia_url" if "en_wikipedia_url" in place_cols \
                     else "en_wikipedia_url_original_country_name"
    place_lookup = _load_place_lookup(
        conn, f"SELECT id, name_en, lon, lat, {place_url_col} FROM places"
    )
    coc_lookup = _load_place_lookup(
        conn,
        "SELECT wikidata_id, name_en, lon, lat, en_wikipedia_url FROM country_of_citizenship",
    )
    print(f"  place lookup: {len(place_lookup):,} | coc lookup: {len(coc_lookup):,}")
    timings["load_refs"] = time.perf_counter() - t

    # 2. Floruit ranges per individual
    t = time.perf_counter()
    floruit_range = {}
    for wid, fs, fe, fy in conn.execute(
        "SELECT wikidata_id, floruit_period_start, floruit_period_end, floruit_year "
        "FROM individuals_floruit_period"
    ):
        if fs is not None and fe is not None:
            floruit_range[wid] = (fs, fe)
        elif fy is not None:
            floruit_range[wid] = (fy, fy)
    year_ranges = {}
    for pid, fy, ty in conn.execute(
        "SELECT polity_id, from_year, to_year FROM polities_periods_cliopatria"
    ):
        year_ranges.setdefault(pid, []).append((fy, ty))
    timings["load_floruit"] = time.perf_counter() - t
    print(f"  floruit ranges: {len(floruit_range):,}  [{timings['load_floruit']:.2f}s]")

    # 3. Build location -> candidate-period indices (one STRtree shared)
    t = time.perf_counter()
    tree = STRtree([pp["geom"] for pp in periods])
    coc_polygon_index = _build_polygon_index(periods, coc_lookup, "coc polygons", tree=tree)
    place_polygon_index = _build_polygon_index(periods, place_lookup, "place polygons", tree=tree)
    url_polity_index = _build_url_index(url_to_polities, year_ranges)
    timings["build_indices"] = time.perf_counter() - t

    # 4. Match every individual
    t = time.perf_counter()
    indiv_cols = {r[1] for r in conn.execute("PRAGMA table_info(individuals)").fetchall()}
    has_inline_ids = {"birthcity_id", "deathcity_id", "country_of_citizenship_ids"}.issubset(indiv_cols)
    has_keys = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='individuals_keys'"
    ).fetchone() is not None
    if has_inline_ids:
        rows_iter = conn.execute(
            "SELECT wikidata_id, name_en, birthcity_id, deathcity_id, "
            "       country_of_citizenship_ids FROM individuals"
        )
    elif has_keys:
        rows_iter = conn.execute(
            "SELECT i.wikidata_id, i.name_en, k.birthcity_id, k.deathcity_id, "
            "       k.country_of_citizenship_ids "
            "FROM individuals i LEFT JOIN individuals_keys k ON i.wikidata_id = k.wikidata_id"
        )
    else:
        sys.exit("no birthcity_id/deathcity_id columns or individuals_keys side-table")
    total = conn.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]

    out_rows = []  # list of dicts -> Polars DF -> CSV

    def _try_year_steps(coc_ids, birth_id, death_id, fstart, fend):
        if coc_ids:
            for coc_id in coc_ids.split(";"):
                coc_id = coc_id.strip()
                if not coc_id:
                    continue
                info = coc_lookup.get(coc_id)
                if not info:
                    continue
                pols = _filter_overlap(coc_polygon_index.get(coc_id), fstart, fend)
                if pols:
                    return pols, "country_of_citizenship", info["name_en"], coc_id, "merge_with_polygon"
            for coc_id in coc_ids.split(";"):
                coc_id = coc_id.strip()
                if not coc_id:
                    continue
                info = coc_lookup.get(coc_id)
                if info and info["url"]:
                    pols = _filter_overlap(url_polity_index.get(info["url"]), fstart, fend)
                    if pols:
                        return pols, "country_of_citizenship", info["name_en"], coc_id, "merge_with_url"
        for cid, origin in ((birth_id, "birthplace"), (death_id, "deathplace")):
            if not cid:
                continue
            cid = cid.strip()
            if not cid:
                continue
            info = place_lookup.get(cid)
            if not info:
                continue
            pols = _filter_overlap(place_polygon_index.get(cid), fstart, fend)
            if pols:
                return pols, origin, info["name_en"], cid, "merge_with_polygon"
            if info["url"]:
                pols = _filter_overlap(url_polity_index.get(info["url"]), fstart, fend)
                if pols:
                    return pols, origin, info["name_en"], cid, "merge_with_url"
        return None

    def _try_fallback(coc_ids, birth_id, death_id):
        if coc_ids:
            for coc_id in coc_ids.split(";"):
                coc_id = coc_id.strip()
                if not coc_id:
                    continue
                info = coc_lookup.get(coc_id)
                if info and info["url"]:
                    pols = url_to_polities.get(info["url"])
                    if pols:
                        return list(pols), "country_of_citizenship", info["name_en"], coc_id, "merge_with_url"
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
                    return list(pols), origin, info["name_en"], cid, "merge_with_url"
        return None

    for wid, name_en, birth_id, death_id, coc_ids in tqdm(
        rows_iter, total=total, desc="match", unit="row", smoothing=0.05
    ):
        rng = floruit_range.get(wid)
        match = None
        fstart = fend = None
        if rng is not None:
            fstart, fend = rng
            match = _try_year_steps(coc_ids, birth_id, death_id, fstart, fend)
        if match is None and rng is None:
            match = _try_fallback(coc_ids, birth_id, death_id)
        if match is None:
            continue
        pols, origin, mname, mwid, method = match
        rep_year = (fstart + fend) // 2 if (fstart is not None and fend is not None) else None
        out_rows.append({
            "wikidata_id": wid,
            "name_en": name_en,
            "polity_name": ";".join(p[0] for p in pols),
            "polity_id": ";".join(str(p[1]) for p in pols),
            "origin": origin,
            "matched_name": mname,
            "matched_wikidata_id": mwid,
            "method": method,
            "floruit_year": rep_year,
            "floruit_period_start": fstart,
            "floruit_period_end": fend,
        })
    conn.close()
    timings["match_loop"] = time.perf_counter() - t

    # 5. Write CSV
    t = time.perf_counter()
    df = pl.from_dicts(out_rows) if out_rows else pl.DataFrame(schema={
        "wikidata_id": pl.Utf8, "name_en": pl.Utf8, "polity_name": pl.Utf8,
        "polity_id": pl.Utf8, "origin": pl.Utf8, "matched_name": pl.Utf8,
        "matched_wikidata_id": pl.Utf8, "method": pl.Utf8,
        "floruit_year": pl.Int64, "floruit_period_start": pl.Int64,
        "floruit_period_end": pl.Int64,
    })
    df.write_csv(str(out_path))
    timings["write_csv"] = time.perf_counter() - t

    timings["total"] = time.perf_counter() - t_total

    # Method/origin breakdown
    if df.height:
        breakdown = (
            df.group_by(["origin", "method"])
              .agg(pl.len().alias("n"))
              .sort("n", descending=True)
        )
        print()
        for r in breakdown.iter_rows():
            print(f"    {r[0]:25s} {r[1]:20s} n={r[2]:>10,}")
        n_multi = df["polity_id"].str.contains(";").sum()
        print(f"    multi-polity rows: {n_multi:,}")

    print()
    for k, v in timings.items():
        print(f"  {k:18s} {v:8.2f}s")
    print(
        f"\nDONE matched={df.height:,} -> {out_path} "
        f"({out_path.stat().st_size/1e6:.1f} MB) in {timings['total']:.2f}s"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--out", default=str(OUT_DIR / "individuals_cliopatria.csv"))
    args = ap.parse_args()
    run(Path(args.db), Path(args.out))


if __name__ == "__main__":
    main()
