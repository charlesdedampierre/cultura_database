// 04 — Build `individuals_cliopatria` (Rust + DuckDB).
//
// One row per matched individual; one polity per individual.
//
// Location selection (best to worst): deathplace, birthplace, country_of_citizenship.
// Linkage to a Cliopatria polity is a two-phase procedure:
//
//   Phase 1 — polygon matching, applied in death → birth → CoC order.
//     For the candidate location's coords, restrict polity-periods to those
//     whose [from_year, to_year] contains the impact year, bbox-prefilter via
//     R-tree, then ray-cast point-in-polygon. When several polities match
//     (e.g. a city falls inside both a kingdom and a wider empire), the polity
//     with the smallest bbox area wins. As soon as one location yields a hit,
//     we stop.
//
//   Phase 2 — Wikipedia URL matching, applied only to individuals still
//     unmatched after phase 1. URL priority is CoC → deathplace → birthplace,
//     joined to `polities_cliopatria.wikipedia_url` and restricted to
//     polity-periods that contain the impact year.
//
// Impact year = midpoint(floruit_period_start, floruit_period_end) when both
// are present, else `floruit_year`. Individuals with no impact year are skipped.
//
// Writes table `individuals_cliopatria` into data/humans_clean.duckdb via the
// DuckDB Appender API. The existing table is dropped and rebuilt.

use anyhow::{Context, Result};
use clap::Parser;
use duckdb::{params, Connection};
use geo::{
    algorithm::{bounding_rect::BoundingRect, contains::Contains, simplify::Simplify},
    Point, Polygon,
};
use rayon::prelude::*;
use rstar::{primitives::GeomWithData, primitives::Rectangle, RTree, AABB};
use std::collections::HashMap;
use std::path::PathBuf;
use std::time::Instant;

#[derive(Parser, Debug)]
struct Args {
    #[arg(long, default_value = "data/humans_clean.duckdb")]
    db: PathBuf,
    #[arg(long, default_value = "individuals_cliopatria")]
    table: String,
}

#[derive(Clone)]
struct Period {
    polity_id: i64,
    polity_name: String,
    from_year: i32,
    to_year: i32,
    bbox_area: f64,
}

struct PolyEntry {
    period_idx: u32,
    polygon: Polygon<f64>,
}

#[derive(Clone)]
struct UrlPeriod {
    polity_id: i64,
    polity_name: String,
    from_year: i32,
    to_year: i32,
}

struct Potentials {
    wikidata_id: String,
    floruit_year: i32,
    polygon_deathplace: bool,
    polygon_birthplace: bool,
    polygon_country_of_citizenship: bool,
    url_country_of_citizenship: bool,
    url_deathplace: bool,
    url_birthplace: bool,
}

type SpatialItem = GeomWithData<Rectangle<[f64; 2]>, u32>;

fn parse_geojson_polygons(s: &str) -> Vec<Polygon<f64>> {
    let geom: geojson::Geometry = match serde_json::from_str(s) {
        Ok(g) => g,
        Err(_) => return Vec::new(),
    };
    let geo_geom: geo_types::Geometry<f64> = match geom.try_into() {
        Ok(g) => g,
        Err(_) => return Vec::new(),
    };
    match geo_geom {
        geo_types::Geometry::Polygon(p) => vec![p],
        geo_types::Geometry::MultiPolygon(mp) => mp.0,
        _ => Vec::new(),
    }
}

fn bbox_area(polys: &[Polygon<f64>]) -> f64 {
    let mut min_x = f64::INFINITY;
    let mut min_y = f64::INFINITY;
    let mut max_x = f64::NEG_INFINITY;
    let mut max_y = f64::NEG_INFINITY;
    for p in polys {
        if let Some(rect) = p.bounding_rect() {
            min_x = min_x.min(rect.min().x);
            min_y = min_y.min(rect.min().y);
            max_x = max_x.max(rect.max().x);
            max_y = max_y.max(rect.max().y);
        }
    }
    if !min_x.is_finite() {
        return f64::INFINITY;
    }
    (max_x - min_x) * (max_y - min_y)
}

fn rect_for_polygon(p: &Polygon<f64>) -> Option<Rectangle<[f64; 2]>> {
    let r = p.bounding_rect()?;
    Some(Rectangle::from_corners(
        [r.min().x, r.min().y],
        [r.max().x, r.max().y],
    ))
}

fn split_ids(s: &str) -> Vec<&str> {
    s.split(';')
        .map(|x| x.trim())
        .filter(|x| !x.is_empty())
        .collect()
}

fn main() -> Result<()> {
    let args = Args::parse();
    let t_total = Instant::now();
    println!("db: {}", args.db.display());
    println!("target table: {}", args.table);
    println!();

    let conn = Connection::open(&args.db)
        .with_context(|| format!("opening duckdb at {}", args.db.display()))?;
    conn.execute_batch("PRAGMA threads=0;").ok();

    // ---------------------------------------------------------------
    // 1. polities + period years + geometries
    // ---------------------------------------------------------------
    let mut t = Instant::now();

    let mut polity_name: HashMap<i64, String> = HashMap::new();
    let mut polity_url: HashMap<i64, String> = HashMap::new();
    {
        let mut stmt = conn.prepare("SELECT id, name, wikipedia_url FROM polities_cliopatria")?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, Option<String>>(1)?.unwrap_or_default(),
                r.get::<_, Option<String>>(2)?.unwrap_or_default(),
            ))
        })?;
        for row in rows {
            let (id, name, url) = row?;
            polity_name.insert(id, name);
            if !url.is_empty() {
                polity_url.insert(id, url);
            }
        }
    }
    let n_polities = polity_name.len();

    let mut periods: Vec<Period> = Vec::new();
    let mut polys: Vec<PolyEntry> = Vec::new();
    let mut tree_items: Vec<SpatialItem> = Vec::new();
    let mut polity_period_years: HashMap<i64, Vec<(i32, i32)>> = HashMap::new();

    {
        let mut stmt = conn.prepare(
            "SELECT polity_id, polity_name, from_year, to_year, geometry \
             FROM polities_periods_cliopatria",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, Option<String>>(1)?.unwrap_or_default(),
                r.get::<_, Option<i64>>(2)?,
                r.get::<_, Option<i64>>(3)?,
                r.get::<_, Option<String>>(4)?,
            ))
        })?;
        for row in rows {
            let (polity_id, period_name, fy, ty, geom_text) = row?;
            let from_year = match fy {
                Some(v) => v as i32,
                None => continue,
            };
            let to_year = match ty {
                Some(v) => v as i32,
                None => continue,
            };
            polity_period_years
                .entry(polity_id)
                .or_default()
                .push((from_year, to_year));

            let Some(geom_text) = geom_text else { continue };
            if geom_text.is_empty() {
                continue;
            }
            let raw_polys = parse_geojson_polygons(&geom_text);
            if raw_polys.is_empty() {
                continue;
            }
            let area = bbox_area(&raw_polys);
            let polity_label = polity_name
                .get(&polity_id)
                .cloned()
                .filter(|n| !n.is_empty())
                .unwrap_or(period_name);

            let period_idx = periods.len() as u32;
            periods.push(Period {
                polity_id,
                polity_name: polity_label,
                from_year,
                to_year,
                bbox_area: area,
            });
            for raw in raw_polys {
                let simplified = raw.simplify(0.01_f64);
                let Some(rect) = rect_for_polygon(&simplified) else {
                    continue;
                };
                let poly_idx = polys.len() as u32;
                polys.push(PolyEntry {
                    period_idx,
                    polygon: simplified,
                });
                tree_items.push(SpatialItem::new(rect, poly_idx));
            }
        }
    }
    let load_periods = t.elapsed();
    println!(
        "  polities={} periods={} polys={} [{:.2}s]",
        n_polities,
        periods.len(),
        polys.len(),
        load_periods.as_secs_f64()
    );

    // ---------------------------------------------------------------
    // 2. R-tree (precomputed bounding boxes for all polity-periods)
    // ---------------------------------------------------------------
    t = Instant::now();
    let tree = RTree::bulk_load(tree_items);
    let build_rtree = t.elapsed();
    println!("  R-tree built [{:.2}s]", build_rtree.as_secs_f64());

    // ---------------------------------------------------------------
    // 3. places + country_of_citizenship lookups
    // ---------------------------------------------------------------
    t = Instant::now();

    struct LocCoord {
        id: String,
        lon: f64,
        lat: f64,
    }

    let mut place_coord: Vec<LocCoord> = Vec::new();
    let mut place_name: HashMap<String, String> = HashMap::new();
    let mut place_url_map: HashMap<String, (String, String)> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT id, name_en, lon, lat, en_wikipedia_url_original_country_name FROM places",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, Option<String>>(0)?.unwrap_or_default(),
                r.get::<_, Option<String>>(1)?.unwrap_or_default(),
                r.get::<_, Option<f64>>(2)?,
                r.get::<_, Option<f64>>(3)?,
                r.get::<_, Option<String>>(4)?.unwrap_or_default(),
            ))
        })?;
        for row in rows {
            let (id, name, lon, lat, url) = row?;
            if id.is_empty() {
                continue;
            }
            place_name.entry(id.clone()).or_insert_with(|| name.clone());
            if let (Some(lon), Some(lat)) = (lon, lat) {
                place_coord.push(LocCoord {
                    id: id.clone(),
                    lon,
                    lat,
                });
            }
            if !url.is_empty() {
                place_url_map.entry(id).or_insert_with(|| (name, url));
            }
        }
    }

    let mut coc_coord: Vec<LocCoord> = Vec::new();
    let mut coc_name: HashMap<String, String> = HashMap::new();
    let mut coc_url_map: HashMap<String, (String, String)> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT wikidata_id, name_en, lon, lat, en_wikipedia_url FROM country_of_citizenship",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, Option<String>>(0)?.unwrap_or_default(),
                r.get::<_, Option<String>>(1)?.unwrap_or_default(),
                r.get::<_, Option<f64>>(2)?,
                r.get::<_, Option<f64>>(3)?,
                r.get::<_, Option<String>>(4)?.unwrap_or_default(),
            ))
        })?;
        for row in rows {
            let (id, name, lon, lat, url) = row?;
            if id.is_empty() {
                continue;
            }
            coc_name.entry(id.clone()).or_insert_with(|| name.clone());
            if let (Some(lon), Some(lat)) = (lon, lat) {
                coc_coord.push(LocCoord {
                    id: id.clone(),
                    lon,
                    lat,
                });
            }
            if !url.is_empty() {
                coc_url_map.entry(id).or_insert_with(|| (name, url));
            }
        }
    }
    let load_locations = t.elapsed();
    println!(
        "  places(coords)={} coc(coords)={} place_url={} coc_url={} [{:.2}s]",
        place_coord.len(),
        coc_coord.len(),
        place_url_map.len(),
        coc_url_map.len(),
        load_locations.as_secs_f64()
    );

    // ---------------------------------------------------------------
    // 4. Spatial join: per ID, list of period indices whose polygon contains it
    // ---------------------------------------------------------------
    t = Instant::now();
    let join_one = |lon: f64, lat: f64| -> Vec<u32> {
        let pt = Point::new(lon, lat);
        let envelope = AABB::from_point([lon, lat]);
        let mut hits: Vec<u32> = Vec::new();
        for item in tree.locate_in_envelope_intersecting(&envelope) {
            let entry = &polys[item.data as usize];
            if entry.polygon.contains(&pt) {
                hits.push(entry.period_idx);
            }
        }
        if hits.len() > 1 {
            hits.sort_unstable();
            hits.dedup();
        }
        hits
    };

    let place_pairs: Vec<(String, Vec<u32>)> = place_coord
        .par_iter()
        .map(|p| (p.id.clone(), join_one(p.lon, p.lat)))
        .filter(|(_, v)| !v.is_empty())
        .collect();
    let coc_pairs: Vec<(String, Vec<u32>)> = coc_coord
        .par_iter()
        .map(|c| (c.id.clone(), join_one(c.lon, c.lat)))
        .filter(|(_, v)| !v.is_empty())
        .collect();

    let n_pp: usize = place_pairs.iter().map(|(_, v)| v.len()).sum();
    let n_cp: usize = coc_pairs.iter().map(|(_, v)| v.len()).sum();
    let spatial_join = t.elapsed();
    println!(
        "  place_poly hits={} coc_poly hits={} [{:.2}s]",
        n_pp,
        n_cp,
        spatial_join.as_secs_f64()
    );

    let place_poly_index: HashMap<String, Vec<u32>> = place_pairs.into_iter().collect();
    let coc_poly_index: HashMap<String, Vec<u32>> = coc_pairs.into_iter().collect();

    // ---------------------------------------------------------------
    // 5. URL → polity-period(s) index
    // ---------------------------------------------------------------
    t = Instant::now();
    let mut url_periods: HashMap<String, Vec<UrlPeriod>> = HashMap::new();
    for (pid, url) in &polity_url {
        let Some(years) = polity_period_years.get(pid) else {
            continue;
        };
        let name = polity_name.get(pid).cloned().unwrap_or_default();
        let bucket = url_periods.entry(url.clone()).or_default();
        for (fy, ty) in years {
            bucket.push(UrlPeriod {
                polity_id: *pid,
                polity_name: name.clone(),
                from_year: *fy,
                to_year: *ty,
            });
        }
    }
    let n_url: usize = url_periods.values().map(|v| v.len()).sum();
    let build_url_index = t.elapsed();
    println!(
        "  url_polity rows={} [{:.2}s]",
        n_url,
        build_url_index.as_secs_f64()
    );

    // ---------------------------------------------------------------
    // 6. individuals + keys + floruit period
    // ---------------------------------------------------------------
    t = Instant::now();

    struct Individual {
        wikidata_id: String,
        name_en: String,
        birthcity_id: String,
        deathcity_id: String,
        coc_ids: String,
        floruit_period_start: Option<i64>,
        floruit_period_end: Option<i64>,
        year: Option<i32>,
    }

    let mut individuals: Vec<Individual> = Vec::new();
    {
        let mut stmt = conn.prepare(
            "SELECT i.wikidata_id, i.name_en, \
                    k.birthcity_id, k.deathcity_id, k.country_of_citizenship_ids, \
                    f.floruit_period_start, f.floruit_period_end, f.floruit_year \
             FROM individuals i \
             LEFT JOIN individuals_keys k ON i.wikidata_id = k.wikidata_id \
             LEFT JOIN individuals_floruit_period f ON i.wikidata_id = f.wikidata_id",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, Option<String>>(0)?.unwrap_or_default(),
                r.get::<_, Option<String>>(1)?.unwrap_or_default(),
                r.get::<_, Option<String>>(2)?.unwrap_or_default(),
                r.get::<_, Option<String>>(3)?.unwrap_or_default(),
                r.get::<_, Option<String>>(4)?.unwrap_or_default(),
                r.get::<_, Option<i64>>(5)?,
                r.get::<_, Option<i64>>(6)?,
                r.get::<_, Option<i64>>(7)?,
            ))
        })?;
        for row in rows {
            let (wid, name, b, d, c, fps, fpe, fy) = row?;
            if wid.is_empty() {
                continue;
            }
            let year = if let (Some(s), Some(e)) = (fps, fpe) {
                Some(((s + e) / 2) as i32)
            } else {
                fy.map(|v| v as i32)
            };
            individuals.push(Individual {
                wikidata_id: wid,
                name_en: name,
                birthcity_id: b,
                deathcity_id: d,
                coc_ids: c,
                floruit_period_start: fps,
                floruit_period_end: fpe,
                year,
            });
        }
    }
    let n_with_year = individuals.iter().filter(|i| i.year.is_some()).count();
    let load_individuals = t.elapsed();
    println!(
        "  individuals={} with_year={} [{:.2}s]",
        individuals.len(),
        n_with_year,
        load_individuals.as_secs_f64()
    );

    // ---------------------------------------------------------------
    // 7. Two-phase cascade resolution (parallel)
    // ---------------------------------------------------------------
    //   Phase 1 — polygon: deathplace → birthplace → CoC (smallest bbox / loc)
    //   Phase 2 — URL    : CoC → deathplace → birthplace (only if phase 1 fails)
    // ---------------------------------------------------------------
    t = Instant::now();

    struct Match {
        wikidata_id: String,
        name_en: String,
        polity_id: i64,
        polity_name: String,
        origin: &'static str,
        matched_name: String,
        matched_wikidata_id: String,
        method: &'static str,
        floruit_year: i32,
        floruit_period_start: Option<i64>,
        floruit_period_end: Option<i64>,
    }

    // Smallest-bbox period from a list of period_idx hits, restricted to year.
    let polygon_best = |hits: &[u32], year: i32| -> Option<(u32, f64)> {
        let mut best: Option<(u32, f64)> = None;
        for &pidx in hits {
            let p = &periods[pidx as usize];
            if year >= p.from_year && year <= p.to_year {
                let area = p.bbox_area;
                if best.map_or(true, |(_, b)| area < b) {
                    best = Some((pidx, area));
                }
            }
        }
        best
    };

    let url_match = |url: &str, year: i32| -> Option<&UrlPeriod> {
        let bucket = url_periods.get(url)?;
        bucket
            .iter()
            .find(|e| year >= e.from_year && year <= e.to_year)
    };

    let matches: Vec<Match> = individuals
        .par_iter()
        .filter_map(|ind| {
            let year = ind.year?;

            // -------- Phase 1: polygon --------

            // 1.a deathplace polygon
            let did = ind.deathcity_id.trim();
            if !did.is_empty() {
                if let Some(hits) = place_poly_index.get(did) {
                    if let Some((pidx, _)) = polygon_best(hits, year) {
                        let p = &periods[pidx as usize];
                        return Some(Match {
                            wikidata_id: ind.wikidata_id.clone(),
                            name_en: ind.name_en.clone(),
                            polity_id: p.polity_id,
                            polity_name: p.polity_name.clone(),
                            origin: "deathplace",
                            matched_name: place_name.get(did).cloned().unwrap_or_default(),
                            matched_wikidata_id: did.to_string(),
                            method: "merge_with_polygon",
                            floruit_year: year,
                            floruit_period_start: ind.floruit_period_start,
                            floruit_period_end: ind.floruit_period_end,
                        });
                    }
                }
            }

            // 1.b birthplace polygon
            let bid = ind.birthcity_id.trim();
            if !bid.is_empty() {
                if let Some(hits) = place_poly_index.get(bid) {
                    if let Some((pidx, _)) = polygon_best(hits, year) {
                        let p = &periods[pidx as usize];
                        return Some(Match {
                            wikidata_id: ind.wikidata_id.clone(),
                            name_en: ind.name_en.clone(),
                            polity_id: p.polity_id,
                            polity_name: p.polity_name.clone(),
                            origin: "birthplace",
                            matched_name: place_name.get(bid).cloned().unwrap_or_default(),
                            matched_wikidata_id: bid.to_string(),
                            method: "merge_with_polygon",
                            floruit_year: year,
                            floruit_period_start: ind.floruit_period_start,
                            floruit_period_end: ind.floruit_period_end,
                        });
                    }
                }
            }

            // 1.c country_of_citizenship centroid polygon — smallest bbox across all coc_ids
            let coc_ids = split_ids(&ind.coc_ids);
            if !coc_ids.is_empty() {
                let mut best: Option<(u32, f64, &str)> = None;
                for cid in &coc_ids {
                    if let Some(hits) = coc_poly_index.get(*cid) {
                        if let Some((pidx, area)) = polygon_best(hits, year) {
                            if best.map_or(true, |(_, b, _)| area < b) {
                                best = Some((pidx, area, cid));
                            }
                        }
                    }
                }
                if let Some((pidx, _, cid)) = best {
                    let p = &periods[pidx as usize];
                    return Some(Match {
                        wikidata_id: ind.wikidata_id.clone(),
                        name_en: ind.name_en.clone(),
                        polity_id: p.polity_id,
                        polity_name: p.polity_name.clone(),
                        origin: "country_of_citizenship",
                        matched_name: coc_name.get(cid).cloned().unwrap_or_default(),
                        matched_wikidata_id: cid.to_string(),
                        method: "merge_with_polygon",
                        floruit_year: year,
                        floruit_period_start: ind.floruit_period_start,
                        floruit_period_end: ind.floruit_period_end,
                    });
                }
            }

            // -------- Phase 2: URL --------

            // 2.a CoC URL — first coc_id whose URL has a year-matching polity-period
            for cid in &coc_ids {
                if let Some((cname, curl)) = coc_url_map.get(*cid) {
                    if let Some(up) = url_match(curl, year) {
                        return Some(Match {
                            wikidata_id: ind.wikidata_id.clone(),
                            name_en: ind.name_en.clone(),
                            polity_id: up.polity_id,
                            polity_name: up.polity_name.clone(),
                            origin: "country_of_citizenship",
                            matched_name: cname.clone(),
                            matched_wikidata_id: cid.to_string(),
                            method: "merge_with_url",
                            floruit_year: year,
                            floruit_period_start: ind.floruit_period_start,
                            floruit_period_end: ind.floruit_period_end,
                        });
                    }
                }
            }

            // 2.b deathplace URL
            if !did.is_empty() {
                if let Some((pn, purl)) = place_url_map.get(did) {
                    if let Some(up) = url_match(purl, year) {
                        return Some(Match {
                            wikidata_id: ind.wikidata_id.clone(),
                            name_en: ind.name_en.clone(),
                            polity_id: up.polity_id,
                            polity_name: up.polity_name.clone(),
                            origin: "deathplace",
                            matched_name: pn.clone(),
                            matched_wikidata_id: did.to_string(),
                            method: "merge_with_url",
                            floruit_year: year,
                            floruit_period_start: ind.floruit_period_start,
                            floruit_period_end: ind.floruit_period_end,
                        });
                    }
                }
            }

            // 2.c birthplace URL
            if !bid.is_empty() {
                if let Some((pn, purl)) = place_url_map.get(bid) {
                    if let Some(up) = url_match(purl, year) {
                        return Some(Match {
                            wikidata_id: ind.wikidata_id.clone(),
                            name_en: ind.name_en.clone(),
                            polity_id: up.polity_id,
                            polity_name: up.polity_name.clone(),
                            origin: "birthplace",
                            matched_name: pn.clone(),
                            matched_wikidata_id: bid.to_string(),
                            method: "merge_with_url",
                            floruit_year: year,
                            floruit_period_start: ind.floruit_period_start,
                            floruit_period_end: ind.floruit_period_end,
                        });
                    }
                }
            }

            None
        })
        .collect();

    let cascade_resolve = t.elapsed();
    println!(
        "  matched individuals: {} [{:.2}s]",
        matches.len(),
        cascade_resolve.as_secs_f64()
    );

    // ---------------------------------------------------------------
    // 7b. Potentials — for each dated individual, record whether each
    //     of the 6 signals would *independently* match a polity, ignoring
    //     cascade ordering. Same helpers as phase 1 / phase 2.
    // ---------------------------------------------------------------
    t = Instant::now();
    let potentials: Vec<Potentials> = individuals
        .par_iter()
        .filter_map(|ind| {
            let year = ind.year?;
            let did = ind.deathcity_id.trim();
            let bid = ind.birthcity_id.trim();
            let coc_ids = split_ids(&ind.coc_ids);

            let polygon_death = !did.is_empty()
                && place_poly_index
                    .get(did)
                    .map_or(false, |h| polygon_best(h, year).is_some());
            let polygon_birth = !bid.is_empty()
                && place_poly_index
                    .get(bid)
                    .map_or(false, |h| polygon_best(h, year).is_some());
            let polygon_coc = coc_ids.iter().any(|cid| {
                coc_poly_index
                    .get(*cid)
                    .map_or(false, |h| polygon_best(h, year).is_some())
            });
            let url_coc = coc_ids.iter().any(|cid| {
                coc_url_map
                    .get(*cid)
                    .map_or(false, |(_, url)| url_match(url, year).is_some())
            });
            let url_death = !did.is_empty()
                && place_url_map
                    .get(did)
                    .map_or(false, |(_, url)| url_match(url, year).is_some());
            let url_birth = !bid.is_empty()
                && place_url_map
                    .get(bid)
                    .map_or(false, |(_, url)| url_match(url, year).is_some());

            Some(Potentials {
                wikidata_id: ind.wikidata_id.clone(),
                floruit_year: year,
                polygon_deathplace: polygon_death,
                polygon_birthplace: polygon_birth,
                polygon_country_of_citizenship: polygon_coc,
                url_country_of_citizenship: url_coc,
                url_deathplace: url_death,
                url_birthplace: url_birth,
            })
        })
        .collect();
    let potentials_t = t.elapsed();
    println!(
        "  potentials computed: {} [{:.2}s]",
        potentials.len(),
        potentials_t.as_secs_f64()
    );

    // ---------------------------------------------------------------
    // 8. Write to DuckDB
    // ---------------------------------------------------------------
    t = Instant::now();
    conn.execute_batch(&format!("DROP TABLE IF EXISTS {};", args.table))?;
    conn.execute_batch(&format!(
        "CREATE TABLE {} (\
            wikidata_id VARCHAR PRIMARY KEY,\
            name_en VARCHAR,\
            polity_id BIGINT,\
            polity_name VARCHAR,\
            origin VARCHAR,\
            matched_name VARCHAR,\
            matched_wikidata_id VARCHAR,\
            method VARCHAR,\
            floruit_year INTEGER,\
            floruit_period_start INTEGER,\
            floruit_period_end INTEGER\
        );",
        args.table
    ))?;
    {
        let mut appender = conn.appender(&args.table)?;
        for m in &matches {
            appender.append_row(params![
                &m.wikidata_id,
                &m.name_en,
                m.polity_id,
                &m.polity_name,
                m.origin,
                &m.matched_name,
                &m.matched_wikidata_id,
                m.method,
                m.floruit_year,
                m.floruit_period_start,
                m.floruit_period_end,
            ])?;
        }
        appender.flush()?;
    }
    conn.execute_batch(&format!(
        "CREATE INDEX IF NOT EXISTS idx_{0}_polity_id ON {0}(polity_id);",
        args.table
    ))?;
    let write_db = t.elapsed();

    // Potentials table — one row per dated individual, six independence flags.
    let potentials_table = format!("{}_potential", args.table);
    let t_pot = Instant::now();
    conn.execute_batch(&format!("DROP TABLE IF EXISTS {};", potentials_table))?;
    conn.execute_batch(&format!(
        "CREATE TABLE {} (\
            wikidata_id VARCHAR PRIMARY KEY,\
            floruit_year INTEGER,\
            polygon_deathplace BOOLEAN,\
            polygon_birthplace BOOLEAN,\
            polygon_country_of_citizenship BOOLEAN,\
            url_country_of_citizenship BOOLEAN,\
            url_deathplace BOOLEAN,\
            url_birthplace BOOLEAN\
        );",
        potentials_table
    ))?;
    {
        let mut appender = conn.appender(&potentials_table)?;
        for p in &potentials {
            appender.append_row(params![
                &p.wikidata_id,
                p.floruit_year,
                p.polygon_deathplace,
                p.polygon_birthplace,
                p.polygon_country_of_citizenship,
                p.url_country_of_citizenship,
                p.url_deathplace,
                p.url_birthplace,
            ])?;
        }
        appender.flush()?;
    }
    let write_potentials = t_pot.elapsed();
    println!(
        "  wrote {} ({} rows) [{:.2}s]",
        potentials_table,
        potentials.len(),
        write_potentials.as_secs_f64()
    );

    // Non-recursive coverage summary
    let n = potentials.len() as f64;
    let pct = |c: usize| (c as f64) / n * 100.0;
    let n_pd = potentials.iter().filter(|p| p.polygon_deathplace).count();
    let n_pb = potentials.iter().filter(|p| p.polygon_birthplace).count();
    let n_pc = potentials.iter().filter(|p| p.polygon_country_of_citizenship).count();
    let n_uc = potentials.iter().filter(|p| p.url_country_of_citizenship).count();
    let n_ud = potentials.iter().filter(|p| p.url_deathplace).count();
    let n_ub = potentials.iter().filter(|p| p.url_birthplace).count();
    println!();
    println!(
        "  Non-recursive potential coverage (of {} dated individuals):",
        potentials.len()
    );
    println!(
        "    Polygon · deathplace                n={:>10}  {:5.2}%",
        n_pd,
        pct(n_pd)
    );
    println!(
        "    Polygon · birthplace                n={:>10}  {:5.2}%",
        n_pb,
        pct(n_pb)
    );
    println!(
        "    Polygon · country-of-citizenship    n={:>10}  {:5.2}%",
        n_pc,
        pct(n_pc)
    );
    println!(
        "    URL · country-of-citizenship        n={:>10}  {:5.2}%",
        n_uc,
        pct(n_uc)
    );
    println!(
        "    URL · deathplace                    n={:>10}  {:5.2}%",
        n_ud,
        pct(n_ud)
    );
    println!(
        "    URL · birthplace                    n={:>10}  {:5.2}%",
        n_ub,
        pct(n_ub)
    );

    let total = t_total.elapsed();

    // breakdown
    let mut buckets: HashMap<(&str, &str), usize> = HashMap::new();
    for m in &matches {
        *buckets.entry((m.origin, m.method)).or_default() += 1;
    }
    let mut bd: Vec<_> = buckets.into_iter().collect();
    bd.sort_by(|a, b| b.1.cmp(&a.1));
    println!();
    for ((origin, method), n) in &bd {
        println!("    {:25} {:20} n={:>10}", origin, method, n);
    }
    println!();
    println!("  load_periods             {:8.2}s", load_periods.as_secs_f64());
    println!("  build_rtree              {:8.2}s", build_rtree.as_secs_f64());
    println!("  load_locations           {:8.2}s", load_locations.as_secs_f64());
    println!("  spatial_join             {:8.2}s", spatial_join.as_secs_f64());
    println!("  build_url_index          {:8.2}s", build_url_index.as_secs_f64());
    println!("  load_individuals         {:8.2}s", load_individuals.as_secs_f64());
    println!("  cascade_resolve          {:8.2}s", cascade_resolve.as_secs_f64());
    println!("  write_db                 {:8.2}s", write_db.as_secs_f64());
    println!("  total                    {:8.2}s", total.as_secs_f64());
    println!(
        "\nDONE matched={} -> {}::{} in {:.2}s",
        matches.len(),
        args.db.display(),
        args.table,
        total.as_secs_f64()
    );

    Ok(())
}
