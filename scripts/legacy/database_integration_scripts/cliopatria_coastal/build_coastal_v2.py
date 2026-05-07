"""
Build cliopatria V2_coastal: extend each polygon toward the coast so near-sea
urban centers (e.g. Copenhagen, Istanbul) fall inside their polity.

Rule per polygon P:
    extension = buffer(P, D) ∩ coastal_zone  − P
    P_new    = P ∪ extension

coastal_zone = global land strip within D km of the coastline
             = land − buffer(land, −D)

So the rule adds only land that is (a) within D km of P and (b) within D km of
a coastline. Purely inland neighbor territory is excluded because it is > D km
from any coast.

Run from project root inside .venv:
    python database_integration_scripts/cliopatria_coastal/build_coastal_v2.py
"""

from __future__ import annotations

import io
import time
import urllib.request
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely
from shapely.ops import unary_union
from shapely.strtree import STRtree
from shapely.validation import make_valid
from tqdm import tqdm


def _clean(geom):
    """Make a geometry OGC-valid, falling back to buffer(0)."""
    if geom is None or geom.is_empty:
        return geom
    if geom.is_valid:
        return geom
    try:
        fixed = make_valid(geom)
        if fixed.is_valid and not fixed.is_empty:
            return fixed
    except Exception:
        pass
    try:
        return geom.buffer(0)
    except Exception:
        return geom

PROJECT = Path("/Users/charlesdedampierre/Desktop/Rsearch Folder/cultura_database")
INPUT = PROJECT / "data/cliopatria_V2/cliopatria_polities_only_v3.geojson"
OUT_DIR = PROJECT / "data/cliopatria_V2_coastal"
OUT_GEOJSON = OUT_DIR / "cliopatria_polities_only_v3_coastal.geojson"
OUT_DIFF = OUT_DIR / "coastal_fix_report.csv"
LAND_CACHE = OUT_DIR / "ne_10m_land"

D_M = 25_000  # 25 km extension distance
EQUAL_AREA_CRS = "EPSG:6933"  # global equal-area, reasonable metric buffers


def download_natural_earth_land() -> gpd.GeoDataFrame:
    if not LAND_CACHE.exists():
        url = "https://naciscdn.org/naturalearth/10m/physical/ne_10m_land.zip"
        print(f"Downloading Natural Earth 10m land: {url}")
        req = urllib.request.Request(url, headers={"User-Agent": "cliopatria-coastal/1.0"})
        with urllib.request.urlopen(req) as r:
            payload = r.read()
        LAND_CACHE.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            z.extractall(LAND_CACHE)
    shp = next(LAND_CACHE.glob("*.shp"))
    land = gpd.read_file(shp)
    print(f"Loaded {len(land)} land features from {shp.name}")
    return land


def build_coastal_zone(land: gpd.GeoDataFrame) -> shapely.geometry.base.BaseGeometry:
    """Return the global coastal land strip (land within D m of any coast)."""
    print("Dissolving land into a single geometry ...")
    t = time.time()
    land_union = unary_union(land.geometry.values)
    print(f"  dissolve took {time.time()-t:.1f}s")

    print(f"Eroding by {D_M/1000:.0f} km to get land interior ...")
    t = time.time()
    interior = land_union.buffer(-D_M)
    print(f"  erosion took {time.time()-t:.1f}s")

    print("Computing coastal strip = land − interior ...")
    t = time.time()
    coastal = land_union.difference(interior)
    print(f"  diff took {time.time()-t:.1f}s")
    return coastal


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    land = download_natural_earth_land().to_crs(EQUAL_AREA_CRS)
    coastal_zone = build_coastal_zone(land)

    # Spatial index on coastal-zone components for per-polygon fast clipping.
    if coastal_zone.geom_type == "MultiPolygon":
        coastal_parts = list(coastal_zone.geoms)
    else:
        coastal_parts = [coastal_zone]
    print(f"Coastal zone has {len(coastal_parts)} components")
    # Pre-clean coastal parts: prevents topology errors during per-feature union.
    coastal_parts = [_clean(g) for g in coastal_parts]
    coast_tree = STRtree(coastal_parts)

    print(f"Loading cliopatria: {INPUT.name}")
    gdf = gpd.read_file(INPUT)
    src_crs = gdf.crs
    print(f"  {len(gdf)} features, CRS={src_crs}")
    gdf = gdf.to_crs(EQUAL_AREA_CRS)

    new_geoms: list = []
    report_rows: list[dict] = []
    n_changed = 0
    n_skipped = 0

    for idx, row in tqdm(gdf.iterrows(), total=len(gdf), desc="Extending to coast"):
        P = row.geometry
        if P is None or P.is_empty:
            new_geoms.append(P)
            continue
        P = _clean(P)

        try:
            buf = P.buffer(D_M)
            hits = coast_tree.query(buf)
            if len(hits) == 0:
                new_geoms.append(P)
                continue
            local_parts = [coastal_parts[i] for i in hits]
            try:
                local_coastal = unary_union(local_parts)
            except Exception:
                # Fall back to cleaning each piece individually.
                local_coastal = unary_union([_clean(g) for g in local_parts])
            ext = buf.intersection(local_coastal)
            ext = _clean(ext)
            if ext.is_empty:
                new_geoms.append(P)
                continue
            try:
                new_P = unary_union([P, ext])
            except Exception:
                # Topology retry: snap invalids away via buffer(0) on both sides.
                new_P = unary_union([P.buffer(0), ext.buffer(0)])
            new_P = _clean(new_P)
        except Exception as e:
            n_skipped += 1
            tqdm.write(f"[skip idx={idx}] {row.get('Name','')}: {e}")
            new_geoms.append(P)
            continue

        added_m2 = new_P.area - P.area
        if added_m2 > 1.0:  # more than 1 m²
            n_changed += 1
            report_rows.append({
                "idx": idx,
                "Name": row.get("Name", ""),
                "FromYear": row.get("FromYear"),
                "ToYear": row.get("ToYear"),
                "SeshatID": row.get("SeshatID", ""),
                "area_before_km2": P.area / 1e6,
                "area_after_km2": new_P.area / 1e6,
                "added_km2": added_m2 / 1e6,
                "pct_added": 100.0 * added_m2 / P.area if P.area > 0 else float("nan"),
            })
        new_geoms.append(new_P)

    gdf["geometry"] = new_geoms
    gdf = gdf.to_crs(src_crs)

    print(f"Writing {OUT_GEOJSON} ...")
    gdf.to_file(OUT_GEOJSON, driver="GeoJSON")
    pd.DataFrame(report_rows).to_csv(OUT_DIFF, index=False)
    print(f"Changed {n_changed} / {len(gdf)} polygons. Skipped (errors): {n_skipped}. Report: {OUT_DIFF}")


if __name__ == "__main__":
    main()
