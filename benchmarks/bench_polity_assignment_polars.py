"""Polity assignment for individuals — Python + DuckDB + Polars + Shapely.

Reads everything from data/humans_clean.duckdb. Writes a CSV (no DB write)
to temp_files/individuals_cliopatria.csv. Times each phase.

Rules (Cliopatria, 2026 spec):

  Phase 1 — Geospatial polygon matching
    Per location with coords, point-in-polygon at the impact year.
    When multiple polities match, the polity with the SMALLEST
    bounding-box area wins (specificity).

  Phase 2 — Wikipedia URL matching (when location lacks coords)
    URL of the location → polity via polities_cliopatria.wikipedia_url,
    keep only periods whose [from_year, to_year] contains the impact year.

  Cascade across locations (first non-empty source wins per individual):
    1. country_of_citizenship  polygon  (smallest bbox)
    2. country_of_citizenship  url
    3. deathplace              polygon  (smallest bbox)
    4. deathplace              url
    5. birthplace              polygon  (smallest bbox)
    6. birthplace              url

Impact year for each individual:
    midpoint of (floruit_period_start, floruit_period_end) when both
    present, else floruit_year. Individuals with no impact year are
    not matched by this benchmark.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import duckdb
import polars as pl
import shapely
from shapely.geometry import shape
from shapely.strtree import STRtree

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO / "data" / "humans_clean.duckdb"
OUT_DIR = REPO / "temp_files"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--out", default=str(OUT_DIR / "individuals_cliopatria.csv"))
    args = ap.parse_args()

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    timings: dict[str, float] = {}
    t_total = time.perf_counter()
    print(f"db: {args.db}\nout: {args.out}\n")

    con = duckdb.connect(args.db, read_only=True)

    # ----------------------------------------------------------- 1. ref data
    t = time.perf_counter()
    polities = con.execute(
        "SELECT id AS polity_id, name AS polity_name, wikipedia_url "
        "FROM polities_cliopatria"
    ).pl()
    name_map = dict(zip(polities["polity_id"].to_list(),
                        polities["polity_name"].to_list()))

    periods = con.execute("""
        SELECT polity_id, polity_name, from_year, to_year, geometry
        FROM polities_periods_cliopatria
        WHERE geometry IS NOT NULL AND geometry <> ''
    """).pl()

    places = con.execute("""
        SELECT id AS place_id, name_en, lon, lat,
               COALESCE(en_wikipedia_url_original_country_name, '') AS url
        FROM places
        WHERE lon IS NOT NULL AND lat IS NOT NULL
    """).pl()
    places_url_only = con.execute("""
        SELECT id AS place_id, name_en, en_wikipedia_url_original_country_name AS url
        FROM places
        WHERE en_wikipedia_url_original_country_name IS NOT NULL
          AND en_wikipedia_url_original_country_name <> ''
    """).pl()

    coc = con.execute("""
        SELECT wikidata_id AS coc_id, name_en, lon, lat,
               COALESCE(en_wikipedia_url, '') AS url
        FROM country_of_citizenship
        WHERE lon IS NOT NULL AND lat IS NOT NULL
    """).pl()
    coc_url_only = con.execute("""
        SELECT wikidata_id AS coc_id, name_en, en_wikipedia_url AS url
        FROM country_of_citizenship
        WHERE en_wikipedia_url IS NOT NULL AND en_wikipedia_url <> ''
    """).pl()

    timings["load_refs"] = time.perf_counter() - t
    print(f"  polities={polities.height:,} periods={periods.height:,} "
          f"places(coords)={places.height:,} coc(coords)={coc.height:,} "
          f"[{timings['load_refs']:.2f}s]")

    # ----------------------------------------------------------- 2. STRtree + bbox area
    t = time.perf_counter()
    geoms = []
    keep = []
    for i, g_str in enumerate(periods["geometry"].to_list()):
        try:
            geoms.append(shape(json.loads(g_str)))
            keep.append(i)
        except Exception:
            continue
    periods = periods[keep].drop("geometry")
    bbox_areas = []
    for g in geoms:
        minx, miny, maxx, maxy = g.bounds
        bbox_areas.append((maxx - minx) * (maxy - miny))
    periods = periods.with_columns(
        pl.Series("bbox_area", bbox_areas, dtype=pl.Float64)
    )
    # canonicalise polity_name from polities_cliopatria
    periods = periods.with_columns(
        pl.col("polity_id").map_elements(
            lambda pid: name_map.get(pid),
            return_dtype=pl.Utf8,
        ).fill_null(pl.col("polity_name")).alias("polity_name")
    )
    tree = STRtree(geoms)
    timings["build_tree"] = time.perf_counter() - t
    print(f"  STRtree built over {len(geoms):,} geometries, "
          f"bbox areas computed [{timings['build_tree']:.2f}s]")

    # ----------------------------------------------------------- 3. spatial joins
    def spatial_join(lookup: pl.DataFrame, key_col: str) -> pl.DataFrame:
        if lookup.height == 0:
            return pl.DataFrame(schema={
                key_col: pl.Utf8, "polity_id": pl.Int64, "polity_name": pl.Utf8,
                "from_year": pl.Int64, "to_year": pl.Int64, "bbox_area": pl.Float64,
            })
        keys = lookup[key_col].to_numpy()
        pts = shapely.points(lookup["lon"].to_numpy(), lookup["lat"].to_numpy())
        pairs = tree.query(pts, predicate="within")
        if pairs.shape[1] == 0:
            return pl.DataFrame(schema={
                key_col: pl.Utf8, "polity_id": pl.Int64, "polity_name": pl.Utf8,
                "from_year": pl.Int64, "to_year": pl.Int64, "bbox_area": pl.Float64,
            })
        pi = pairs[0].tolist(); ji = pairs[1].tolist()
        pid = periods["polity_id"].to_numpy()
        pname = periods["polity_name"].to_numpy()
        fy = periods["from_year"].to_numpy()
        ty = periods["to_year"].to_numpy()
        bba = periods["bbox_area"].to_numpy()
        return pl.DataFrame({
            key_col:        [keys[i] for i in pi],
            "polity_id":    [int(pid[j]) for j in ji],
            "polity_name":  [str(pname[j]) for j in ji],
            "from_year":    [int(fy[j]) for j in ji],
            "to_year":      [int(ty[j]) for j in ji],
            "bbox_area":    [float(bba[j]) for j in ji],
        })

    t = time.perf_counter()
    coc_poly = spatial_join(coc.select(["coc_id", "lon", "lat"]), "coc_id")
    place_poly = spatial_join(places.select(["place_id", "lon", "lat"]), "place_id")
    timings["spatial_join"] = time.perf_counter() - t
    print(f"  coc_poly hits={coc_poly.height:,} place_poly hits={place_poly.height:,} "
          f"[{timings['spatial_join']:.2f}s]")

    # ----------------------------------------------------------- 4. URL index (year-aware)
    t = time.perf_counter()
    period_year = con.execute(
        "SELECT polity_id, from_year, to_year FROM polities_periods_cliopatria"
    ).pl()
    url_polity = (
        polities.filter(pl.col("wikipedia_url").is_not_null() & (pl.col("wikipedia_url") != ""))
                .rename({"wikipedia_url": "url"})
                .join(period_year, on="polity_id", how="inner")
                .select(["url", "polity_id", "polity_name", "from_year", "to_year"])
    )
    timings["build_url_index"] = time.perf_counter() - t
    print(f"  url_polity rows={url_polity.height:,} "
          f"[{timings['build_url_index']:.2f}s]")

    # ----------------------------------------------------------- 5. individuals
    t = time.perf_counter()
    indiv = con.execute("""
        SELECT i.wikidata_id, i.name_en,
               k.birthcity_id, k.deathcity_id, k.country_of_citizenship_ids,
               f.floruit_period_start, f.floruit_period_end, f.floruit_year
        FROM individuals i
        LEFT JOIN individuals_keys k ON i.wikidata_id = k.wikidata_id
        LEFT JOIN individuals_floruit_period f ON i.wikidata_id = f.wikidata_id
    """).pl()
    con.close()
    indiv = indiv.with_columns(
        pl.coalesce(
            ((pl.col("floruit_period_start") + pl.col("floruit_period_end")) / 2)
                .cast(pl.Int64, strict=False),
            pl.col("floruit_year"),
        ).alias("year")
    )
    n_with_year = indiv.filter(pl.col("year").is_not_null()).height
    timings["load_individuals"] = time.perf_counter() - t
    print(f"  individuals={indiv.height:,} with_year={n_with_year:,} "
          f"[{timings['load_individuals']:.2f}s]")

    # ----------------------------------------------------------- 6. priority cascade
    t = time.perf_counter()

    base = indiv.select([
        "wikidata_id", "name_en",
        "birthcity_id", "deathcity_id", "country_of_citizenship_ids",
        "year", "floruit_period_start", "floruit_period_end",
    ]).filter(pl.col("year").is_not_null())

    # Per priority level we produce: wikidata_id -> single best (polity_id, polity_name,
    # origin, method, matched_name, matched_wikidata_id). Smallest bbox wins inside polygon.

    def coc_polygon_matches() -> pl.DataFrame:
        coc_long = (
            base.with_columns(pl.col("country_of_citizenship_ids").str.split(";").alias("_l"))
                .explode("_l")
                .with_columns(pl.col("_l").str.strip_chars().alias("coc_id"))
                .filter(pl.col("coc_id").is_not_null() & (pl.col("coc_id") != ""))
                .drop("_l")
        )
        joined = (
            coc_long.join(coc_poly, on="coc_id", how="inner")
                    .filter((pl.col("year") >= pl.col("from_year")) &
                            (pl.col("year") <= pl.col("to_year")))
                    .join(coc.select(["coc_id", "name_en"]).rename({"name_en": "matched_name"}),
                          on="coc_id", how="left")
        )
        if joined.height == 0:
            return joined
        # Smallest bbox per (wikidata_id) wins.
        return (
            joined.sort("bbox_area")
                  .unique(subset=["wikidata_id"], keep="first", maintain_order=True)
                  .with_columns(
                      pl.lit("country_of_citizenship").alias("origin"),
                      pl.lit("merge_with_polygon").alias("method"),
                      pl.col("coc_id").alias("matched_wikidata_id"),
                  )
        )

    def coc_url_matches() -> pl.DataFrame:
        coc_long = (
            base.with_columns(pl.col("country_of_citizenship_ids").str.split(";").alias("_l"))
                .explode("_l")
                .with_columns(pl.col("_l").str.strip_chars().alias("coc_id"))
                .filter(pl.col("coc_id").is_not_null() & (pl.col("coc_id") != ""))
                .drop("_l")
                .join(coc_url_only.select(["coc_id", "name_en", "url"])
                                  .rename({"name_en": "matched_name"}),
                      on="coc_id", how="inner")
        )
        joined = (
            coc_long.join(url_polity, on="url", how="inner")
                    .filter((pl.col("year") >= pl.col("from_year")) &
                            (pl.col("year") <= pl.col("to_year")))
        )
        if joined.height == 0:
            return joined
        return (
            joined.unique(subset=["wikidata_id"], keep="first", maintain_order=True)
                  .with_columns(
                      pl.lit("country_of_citizenship").alias("origin"),
                      pl.lit("merge_with_url").alias("method"),
                      pl.col("coc_id").alias("matched_wikidata_id"),
                  )
        )

    def place_polygon_matches(id_col: str, origin_lbl: str) -> pl.DataFrame:
        joined = (
            base.filter(pl.col(id_col).is_not_null() & (pl.col(id_col) != ""))
                .with_columns(pl.col(id_col).str.strip_chars().alias("place_id"))
                .join(place_poly, on="place_id", how="inner")
                .filter((pl.col("year") >= pl.col("from_year")) &
                        (pl.col("year") <= pl.col("to_year")))
                .join(places.select(["place_id", "name_en"]).rename({"name_en": "matched_name"}),
                      on="place_id", how="left")
        )
        if joined.height == 0:
            return joined
        return (
            joined.sort("bbox_area")
                  .unique(subset=["wikidata_id"], keep="first", maintain_order=True)
                  .with_columns(
                      pl.lit(origin_lbl).alias("origin"),
                      pl.lit("merge_with_polygon").alias("method"),
                      pl.col("place_id").alias("matched_wikidata_id"),
                  )
        )

    def place_url_matches(id_col: str, origin_lbl: str) -> pl.DataFrame:
        joined = (
            base.filter(pl.col(id_col).is_not_null() & (pl.col(id_col) != ""))
                .with_columns(pl.col(id_col).str.strip_chars().alias("place_id"))
                .join(places_url_only.select(["place_id", "name_en", "url"])
                                     .rename({"name_en": "matched_name"}),
                      on="place_id", how="inner")
                .join(url_polity, on="url", how="inner")
                .filter((pl.col("year") >= pl.col("from_year")) &
                        (pl.col("year") <= pl.col("to_year")))
        )
        if joined.height == 0:
            return joined
        return (
            joined.unique(subset=["wikidata_id"], keep="first", maintain_order=True)
                  .with_columns(
                      pl.lit(origin_lbl).alias("origin"),
                      pl.lit("merge_with_url").alias("method"),
                      pl.col("place_id").alias("matched_wikidata_id"),
                  )
        )

    p1 = coc_polygon_matches()
    p2 = coc_url_matches()
    p3 = place_polygon_matches("deathcity_id", "deathplace")
    p4 = place_url_matches("deathcity_id", "deathplace")
    p5 = place_polygon_matches("birthcity_id", "birthplace")
    p6 = place_url_matches("birthcity_id", "birthplace")

    timings["build_priority_tables"] = time.perf_counter() - t
    p_sizes = [p1.height, p2.height, p3.height, p4.height, p5.height, p6.height]
    print(f"  prio sizes (1..6): {p_sizes}  [{timings['build_priority_tables']:.2f}s]")

    # ----------------------------------------------------------- 7. cascade resolution
    t = time.perf_counter()

    keep_cols = ["wikidata_id", "name_en", "polity_id", "polity_name",
                 "origin", "method", "matched_name", "matched_wikidata_id",
                 "year", "floruit_period_start", "floruit_period_end"]

    cascade = pl.DataFrame(schema={c: pl.Utf8 for c in keep_cols})
    cascade = cascade.with_columns(
        pl.col("polity_id").cast(pl.Int64, strict=False),
        pl.col("year").cast(pl.Int64, strict=False),
        pl.col("floruit_period_start").cast(pl.Int64, strict=False),
        pl.col("floruit_period_end").cast(pl.Int64, strict=False),
    )
    matched_set = pl.Series("wikidata_id", [], dtype=pl.Utf8)

    for pdf in (p1, p2, p3, p4, p5, p6):
        if pdf.height == 0:
            continue
        new = (
            pdf.filter(~pl.col("wikidata_id").is_in(matched_set))
               .select(keep_cols)
        )
        if new.height == 0:
            continue
        cascade = pl.concat([cascade, new], how="vertical_relaxed")
        matched_set = pl.concat([matched_set, new["wikidata_id"]])

    timings["cascade_resolve"] = time.perf_counter() - t
    print(f"  matched individuals: {cascade.height:,} "
          f"[{timings['cascade_resolve']:.2f}s]")

    # ----------------------------------------------------------- 8. write CSV
    t = time.perf_counter()
    cascade = cascade.rename({"year": "floruit_year"}).select([
        "wikidata_id", "name_en", "polity_name", "polity_id",
        "origin", "matched_name", "matched_wikidata_id", "method",
        "floruit_year", "floruit_period_start", "floruit_period_end",
    ])
    cascade.write_csv(args.out)
    timings["write_csv"] = time.perf_counter() - t

    timings["total"] = time.perf_counter() - t_total

    bd = (
        cascade.group_by(["origin", "method"])
               .agg(pl.len().alias("n"))
               .sort("n", descending=True)
    )
    print()
    for r in bd.iter_rows():
        print(f"    {r[0]:25s} {r[1]:20s} n={r[2]:>10,}")

    print()
    for k, v in timings.items():
        print(f"  {k:24s} {v:8.2f}s")
    print(
        f"\nDONE matched={cascade.height:,} -> {args.out} "
        f"({Path(args.out).stat().st_size/1e6:.1f} MB) in {timings['total']:.2f}s"
    )


if __name__ == "__main__":
    main()
