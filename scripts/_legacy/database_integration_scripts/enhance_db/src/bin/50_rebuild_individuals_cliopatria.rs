/// Rebuild individuals_cliopatria with new matching priority:
///   1. Nationality-location polygon + impact_year
///   2. Nationality URL + impact_year
///   3. Birth-location polygon + impact_year
///   4. Birth-location country URL + impact_year
///   5. Death-location polygon + impact_year
///   6. Death-location country URL + impact_year
///   7. Fallback (no impact_year): URL matching (nationality -> birth -> death) without year check
///
/// An individual can belong to MULTIPLE overlapping polities at the same time
/// (e.g. "Han" and "(Han)"). All matching polities are stored semicolon-separated
/// in polity_name and polity_id columns.
///
/// Uses polity ID everywhere (not name) to handle duplicate polity names.
/// Reads polity names from polities_cliopatria (latest names from steps 47-49).
/// Also updates polities_cliopatria.number_individuals using polity ID.
use anyhow::Result;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection};
use std::collections::HashMap;
use std::fs;
use std::io::Write;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const TASK_LOG: &str = "task.log";
const BATCH_SIZE: usize = 50_000;

fn log(msg: &str) {
    println!("{}", msg);
    let mut f = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(TASK_LOG)
        .unwrap();
    writeln!(f, "{}", msg).unwrap();
}

fn parse_year(date_str: &str) -> Option<i32> {
    if date_str.starts_with('-') {
        let rest = &date_str[1..];
        let year_str = rest.split('-').next()?;
        let year: i32 = year_str.parse().ok()?;
        Some(-year)
    } else {
        let year_str = date_str.split('-').next()?;
        year_str.parse().ok()
    }
}

fn point_in_polygon(px: f64, py: f64, ring: &[(f64, f64)]) -> bool {
    let n = ring.len();
    if n < 3 {
        return false;
    }
    let mut inside = false;
    let mut j = n - 1;
    for i in 0..n {
        let (xi, yi) = ring[i];
        let (xj, yj) = ring[j];
        if ((yi > py) != (yj > py)) && (px < (xj - xi) * (py - yi) / (yj - yi) + xi) {
            inside = !inside;
        }
        j = i;
    }
    inside
}

fn point_in_geometry(lon: f64, lat: f64, geom_json: &serde_json::Value) -> bool {
    let geom_type = geom_json.get("type").and_then(|t| t.as_str()).unwrap_or("");
    let coords = match geom_json.get("coordinates") {
        Some(c) => c,
        None => return false,
    };
    match geom_type {
        "Polygon" => {
            if let Some(rings) = coords.as_array() {
                if let Some(outer_ring) = rings.first().and_then(|r| r.as_array()) {
                    let ring: Vec<(f64, f64)> = outer_ring
                        .iter()
                        .filter_map(|p| {
                            let arr = p.as_array()?;
                            Some((arr[0].as_f64()?, arr[1].as_f64()?))
                        })
                        .collect();
                    return point_in_polygon(lon, lat, &ring);
                }
            }
            false
        }
        "MultiPolygon" => {
            if let Some(polygons) = coords.as_array() {
                for polygon in polygons {
                    if let Some(rings) = polygon.as_array() {
                        if let Some(outer_ring) = rings.first().and_then(|r| r.as_array()) {
                            let ring: Vec<(f64, f64)> = outer_ring
                                .iter()
                                .filter_map(|p| {
                                    let arr = p.as_array()?;
                                    Some((arr[0].as_f64()?, arr[1].as_f64()?))
                                })
                                .collect();
                            if point_in_polygon(lon, lat, &ring) {
                                return true;
                            }
                        }
                    }
                }
            }
            false
        }
        _ => false,
    }
}

struct BBox {
    min_lon: f64,
    max_lon: f64,
    min_lat: f64,
    max_lat: f64,
}

fn compute_bbox(geom_json: &serde_json::Value) -> Option<BBox> {
    let geom_type = geom_json.get("type")?.as_str()?;
    let coords = geom_json.get("coordinates")?;
    let mut min_lon = f64::MAX;
    let mut max_lon = f64::MIN;
    let mut min_lat = f64::MAX;
    let mut max_lat = f64::MIN;
    let mut update = |lon: f64, lat: f64| {
        if lon < min_lon { min_lon = lon; }
        if lon > max_lon { max_lon = lon; }
        if lat < min_lat { min_lat = lat; }
        if lat > max_lat { max_lat = lat; }
    };
    match geom_type {
        "Polygon" => {
            for ring in coords.as_array()? {
                for pt in ring.as_array()? {
                    let arr = pt.as_array()?;
                    update(arr[0].as_f64()?, arr[1].as_f64()?);
                }
            }
        }
        "MultiPolygon" => {
            for polygon in coords.as_array()? {
                for ring in polygon.as_array()? {
                    for pt in ring.as_array()? {
                        let arr = pt.as_array()?;
                        update(arr[0].as_f64()?, arr[1].as_f64()?);
                    }
                }
            }
        }
        _ => return None,
    }
    Some(BBox { min_lon, max_lon, min_lat, max_lat })
}

struct PolityPeriod {
    polity_id: i64,
    polity_name: String,
    from_year: i32,
    to_year: i32,
    #[allow(dead_code)]
    area: f64,
    bbox: BBox,
    geometry: serde_json::Value,
}

/// Info about a city or nationality, keyed by wikidata_id
struct PlaceInfo {
    name_en: String,
    coords: Option<(f64, f64)>, // (lon, lat)
    url: Option<String>,
}

fn main() -> Result<()> {
    let _ = fs::remove_file(TASK_LOG);
    log("=== Step 50: Rebuild individuals_cliopatria (multi-polity, nationality->birth->death priority) ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // ========================================================
    // PHASE 1: Load polity periods with geometries from main DB
    // ========================================================
    log("[50] Loading polity name lookup from polities_cliopatria...");
    let mut polity_id_to_name: HashMap<i64, String> = HashMap::new();
    {
        let mut stmt = conn.prepare("SELECT id, name FROM polities_cliopatria")?;
        let rows = stmt.query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?)))?;
        for r in rows {
            let (id, name) = r?;
            polity_id_to_name.insert(id, name);
        }
    }
    log(&format!("[50] Polity name lookup: {} entries", polity_id_to_name.len()));

    // URL-to-polity: one URL can map to MULTIPLE polities
    log("[50] Building URL-to-polity lookup from polities_cliopatria...");
    let mut url_to_polities: HashMap<String, Vec<(String, i64)>> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT id, name, wikipedia_url FROM polities_cliopatria WHERE wikipedia_url IS NOT NULL",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?))
        })?;
        for r in rows {
            let (id, name, url) = r?;
            url_to_polities.entry(url).or_default().push((name, id));
        }
    }
    let url_count: usize = url_to_polities.len();
    let multi_url_count: usize = url_to_polities.values().filter(|v| v.len() > 1).count();
    log(&format!("[50] URL-to-polity lookup: {} URLs ({} with multiple polities)", url_count, multi_url_count));

    log("[50] Loading polity periods from cliopatria_polity_periods...");
    let mut periods: Vec<PolityPeriod> = Vec::new();
    {
        let mut stmt = conn.prepare(
            "SELECT polity_id, polity_name, from_year, to_year, area, geometry
             FROM cliopatria_polity_periods WHERE geometry IS NOT NULL",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, i32>(2)?,
                r.get::<_, i32>(3)?,
                r.get::<_, Option<f64>>(4)?,
                r.get::<_, String>(5)?,
            ))
        })?;
        let mut skipped = 0;
        for r in rows {
            let (polity_id, polity_name, from_year, to_year, db_area, geom_str) = r?;
            if let Ok(geom_json) = serde_json::from_str::<serde_json::Value>(&geom_str) {
                if let Some(bbox) = compute_bbox(&geom_json) {
                    let clean_name = polity_id_to_name
                        .get(&polity_id)
                        .cloned()
                        .unwrap_or(polity_name);
                    let area = db_area.unwrap_or_else(|| {
                        (bbox.max_lon - bbox.min_lon) * (bbox.max_lat - bbox.min_lat)
                    });
                    periods.push(PolityPeriod {
                        polity_id,
                        polity_name: clean_name,
                        from_year,
                        to_year,
                        area,
                        bbox,
                        geometry: geom_json,
                    });
                } else {
                    skipped += 1;
                }
            } else {
                skipped += 1;
            }
        }
        log(&format!("[50] Loaded {} polity periods ({} skipped)", periods.len(), skipped));
    }

    // ========================================================
    // PHASE 2: Build lookups keyed by wikidata_id
    // ========================================================

    // City lookup: city wikidata_id -> PlaceInfo
    log("[50] Building city lookup (by wikidata_id)...");
    let mut city_lookup: HashMap<String, PlaceInfo> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT id, name_en, lon, lat, en_wikipedia_url_original_country_name FROM cities",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, Option<String>>(1)?,
                r.get::<_, Option<f64>>(2)?,
                r.get::<_, Option<f64>>(3)?,
                r.get::<_, Option<String>>(4)?,
            ))
        })?;
        for r in rows {
            let (id, name_en, lon, lat, url) = r?;
            let coords = match (lon, lat) {
                (Some(lo), Some(la)) => Some((lo, la)),
                _ => None,
            };
            city_lookup.insert(id, PlaceInfo {
                name_en: name_en.unwrap_or_default(),
                coords,
                url,
            });
        }
    }
    log(&format!("[50] City lookup: {} entries", city_lookup.len()));

    // Nationality lookup: nationality wikidata_id -> PlaceInfo
    log("[50] Building nationality lookup (by wikidata_id)...");
    let mut nat_lookup: HashMap<String, PlaceInfo> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT wikidata_id, name_en, lon, lat, en_wikipedia_url FROM nationalities",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, Option<String>>(1)?,
                r.get::<_, Option<f64>>(2)?,
                r.get::<_, Option<f64>>(3)?,
                r.get::<_, Option<String>>(4)?,
            ))
        })?;
        for r in rows {
            let (wid, name_en, lon, lat, url) = r?;
            let coords = match (lon, lat) {
                (Some(lo), Some(la)) => Some((lo, la)),
                _ => None,
            };
            nat_lookup.insert(wid, PlaceInfo {
                name_en: name_en.unwrap_or_default(),
                coords,
                url,
            });
        }
    }
    log(&format!("[50] Nationality lookup: {} entries", nat_lookup.len()));

    // Impact date lookup: individual wikidata_id -> year
    log("[50] Building impact date lookup...");
    let mut impact_lookup: HashMap<String, i32> = HashMap::new();
    {
        let mut stmt =
            conn.prepare("SELECT wikidata_id, impact_date FROM individuals_impact_date")?;
        let rows = stmt.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))?;
        for r in rows {
            let (wid, date_str) = r?;
            if let Some(year) = parse_year(&date_str) {
                impact_lookup.insert(wid, year);
            }
        }
    }
    log(&format!("[50] Impact date lookup: {} entries", impact_lookup.len()));

    // Polity-id to year-ranges lookup (all periods, not just those with geometry)
    log("[50] Building polity year-range lookup...");
    let mut polity_id_to_years: HashMap<i64, Vec<(i32, i32)>> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT polity_id, from_year, to_year FROM cliopatria_polity_periods",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((r.get::<_, i64>(0)?, r.get::<_, i32>(1)?, r.get::<_, i32>(2)?))
        })?;
        for r in rows {
            let (pid, from, to) = r?;
            polity_id_to_years.entry(pid).or_default().push((from, to));
        }
    }
    log(&format!("[50] Polity year-range lookup: {} polities", polity_id_to_years.len()));

    // ========================================================
    // PHASE 3: Create individuals_cliopatria table
    //   polity_id is TEXT (semicolon-separated) to support multiple polities
    // ========================================================
    log("[50] Dropping and recreating individuals_cliopatria table...");
    conn.execute_batch("DROP TABLE IF EXISTS individuals_cliopatria;")?;
    conn.execute_batch(
        "CREATE TABLE individuals_cliopatria (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            polity_name TEXT,
            polity_id TEXT,
            origin TEXT,
            matched_name TEXT,
            matched_wikidata_id TEXT,
            method TEXT,
            impact_date INTEGER
        );",
    )?;

    // ========================================================
    // PHASE 4: Process all individuals
    // ========================================================
    let total: i64 = conn.query_row("SELECT COUNT(*) FROM individuals", [], |r| r.get(0))?;
    log(&format!("[50] Total individuals to process: {}", total));

    let pb = ProgressBar::new(total as u64);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{msg} [{bar:40}] {pos}/{len} ({eta})")
            .unwrap(),
    );
    pb.set_message("Matching individuals to cliopatria");

    let mut offset: i64 = 0;
    let mut cnt_nat_poly = 0u64;
    let mut cnt_nat_url = 0u64;
    let mut cnt_birth_poly = 0u64;
    let mut cnt_birth_url = 0u64;
    let mut cnt_death_poly = 0u64;
    let mut cnt_death_url = 0u64;
    let mut cnt_fallback_url = 0u64;
    let mut cnt_unmatched = 0u64;
    let mut total_inserted = 0u64;
    let mut cnt_multi_polity = 0u64;

    // Helper: find ALL polities whose polygon contains (lon,lat) at the given year.
    // Returns all matches deduplicated by polity_id.
    let find_all_polities_by_polygon =
        |lon: f64, lat: f64, year: i32| -> Vec<(String, i64)> {
            let mut results: Vec<(String, i64)> = Vec::new();
            for pp in &periods {
                if year < pp.from_year || year > pp.to_year {
                    continue;
                }
                if lon < pp.bbox.min_lon
                    || lon > pp.bbox.max_lon
                    || lat < pp.bbox.min_lat
                    || lat > pp.bbox.max_lat
                {
                    continue;
                }
                if point_in_geometry(lon, lat, &pp.geometry) {
                    results.push((pp.polity_name.clone(), pp.polity_id));
                }
            }
            // Deduplicate by polity_id (same polity may have multiple periods matching)
            results.sort_by_key(|(_, id)| *id);
            results.dedup_by_key(|(_, id)| *id);
            results
        };

    // Helper: find ALL polities matching a URL with valid year range
    let find_all_polities_by_url =
        |url: &str, year: i32| -> Vec<(String, i64)> {
            if let Some(polities) = url_to_polities.get(url) {
                polities
                    .iter()
                    .filter(|(_, pid)| {
                        polity_id_to_years.get(pid).map_or(false, |yrs| {
                            yrs.iter().any(|(from, to)| year >= *from && year <= *to)
                        })
                    })
                    .cloned()
                    .collect()
            } else {
                Vec::new()
            }
        };

    // Helper: find ALL polities matching a URL without year check (fallback)
    let find_all_polities_by_url_no_year =
        |url: &str| -> Vec<(String, i64)> {
            url_to_polities.get(url).cloned().unwrap_or_default()
        };

    loop {
        // Read batch: join individuals with individuals_keys to get wikidata_ids
        let mut batch: Vec<(
            String,            // wikidata_id
            Option<String>,    // name_en
            Option<String>,    // birthcity_id
            Option<String>,    // deathcity_id
            Option<String>,    // nationalities_ids (semicolon-separated)
        )> = Vec::with_capacity(BATCH_SIZE);
        {
            let mut stmt = conn.prepare_cached(
                "SELECT i.wikidata_id, i.name_en, k.birthcity_id, k.deathcity_id, k.nationalities_ids
                 FROM individuals i
                 LEFT JOIN individuals_keys k ON i.wikidata_id = k.wikidata_id
                 ORDER BY i.rowid
                 LIMIT ?1 OFFSET ?2",
            )?;
            let rows = stmt.query_map(params![BATCH_SIZE as i64, offset], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, Option<String>>(1)?,
                    r.get::<_, Option<String>>(2)?,
                    r.get::<_, Option<String>>(3)?,
                    r.get::<_, Option<String>>(4)?,
                ))
            })?;
            for r in rows {
                batch.push(r?);
            }
        }

        if batch.is_empty() {
            break;
        }

        conn.execute_batch("BEGIN TRANSACTION;")?;
        {
            let mut insert = conn.prepare_cached(
                "INSERT OR IGNORE INTO individuals_cliopatria
                 (wikidata_id, name_en, polity_name, polity_id, origin, matched_name, matched_wikidata_id, method, impact_date)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
            )?;

            for (wikidata_id, name_en, birthcity_id, deathcity_id, nationalities_ids) in &batch {
                // matched = (polities, origin, matched_name, matched_wikidata_id, method, impact_date)
                // polities is Vec<(name, id)> - can have multiple entries
                let mut matched: Option<(Vec<(String, i64)>, &str, String, String, &str, Option<i32>)> = None;

                // === WITH IMPACT_YEAR: interleaved polygon + URL ===
                if let Some(&year) = impact_lookup.get(wikidata_id.as_str()) {

                    // Priority 1: Nationality polygon
                    if matched.is_none() {
                        if let Some(nat_ids_str) = nationalities_ids {
                            for nat_id in nat_ids_str.split(';') {
                                let nat_id = nat_id.trim();
                                if nat_id.is_empty() {
                                    continue;
                                }
                                if let Some(nat_info) = nat_lookup.get(nat_id) {
                                    if let Some((lon, lat)) = nat_info.coords {
                                        let polities = find_all_polities_by_polygon(lon, lat, year);
                                        if !polities.is_empty() {
                                            matched = Some((
                                                polities,
                                                "nationality",
                                                nat_info.name_en.clone(),
                                                nat_id.to_string(),
                                                "polygon",
                                                Some(year),
                                            ));
                                            break;
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // Priority 2: Nationality URL
                    if matched.is_none() {
                        if let Some(nat_ids_str) = nationalities_ids {
                            for nat_id in nat_ids_str.split(';') {
                                let nat_id = nat_id.trim();
                                if nat_id.is_empty() {
                                    continue;
                                }
                                if let Some(nat_info) = nat_lookup.get(nat_id) {
                                    if let Some(url) = &nat_info.url {
                                        let polities = find_all_polities_by_url(url, year);
                                        if !polities.is_empty() {
                                            matched = Some((
                                                polities,
                                                "nationality",
                                                nat_info.name_en.clone(),
                                                nat_id.to_string(),
                                                "url",
                                                Some(year),
                                            ));
                                            break;
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // Priority 3: Birthplace polygon
                    if matched.is_none() {
                        if let Some(bc_id) = birthcity_id {
                            let bc_id = bc_id.trim();
                            if !bc_id.is_empty() {
                                if let Some(city_info) = city_lookup.get(bc_id) {
                                    if let Some((lon, lat)) = city_info.coords {
                                        let polities = find_all_polities_by_polygon(lon, lat, year);
                                        if !polities.is_empty() {
                                            matched = Some((
                                                polities,
                                                "birthplace",
                                                city_info.name_en.clone(),
                                                bc_id.to_string(),
                                                "polygon",
                                                Some(year),
                                            ));
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // Priority 4: Birthplace URL
                    if matched.is_none() {
                        if let Some(bc_id) = birthcity_id {
                            let bc_id = bc_id.trim();
                            if !bc_id.is_empty() {
                                if let Some(city_info) = city_lookup.get(bc_id) {
                                    if let Some(url) = &city_info.url {
                                        let polities = find_all_polities_by_url(url, year);
                                        if !polities.is_empty() {
                                            matched = Some((
                                                polities,
                                                "birthplace",
                                                city_info.name_en.clone(),
                                                bc_id.to_string(),
                                                "url",
                                                Some(year),
                                            ));
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // Priority 5: Deathplace polygon
                    if matched.is_none() {
                        if let Some(dc_id) = deathcity_id {
                            let dc_id = dc_id.trim();
                            if !dc_id.is_empty() {
                                if let Some(city_info) = city_lookup.get(dc_id) {
                                    if let Some((lon, lat)) = city_info.coords {
                                        let polities = find_all_polities_by_polygon(lon, lat, year);
                                        if !polities.is_empty() {
                                            matched = Some((
                                                polities,
                                                "deathplace",
                                                city_info.name_en.clone(),
                                                dc_id.to_string(),
                                                "polygon",
                                                Some(year),
                                            ));
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // Priority 6: Deathplace URL
                    if matched.is_none() {
                        if let Some(dc_id) = deathcity_id {
                            let dc_id = dc_id.trim();
                            if !dc_id.is_empty() {
                                if let Some(city_info) = city_lookup.get(dc_id) {
                                    if let Some(url) = &city_info.url {
                                        let polities = find_all_polities_by_url(url, year);
                                        if !polities.is_empty() {
                                            matched = Some((
                                                polities,
                                                "deathplace",
                                                city_info.name_en.clone(),
                                                dc_id.to_string(),
                                                "url",
                                                Some(year),
                                            ));
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                // === FALLBACK: URL matching without year check ===
                // Only for individuals who genuinely have NO impact_year.
                // If they have an impact_year but didn't match above, they stay unmatched.
                if matched.is_none() && !impact_lookup.contains_key(wikidata_id.as_str()) {
                    // Fallback nationality URL
                    if let Some(nat_ids_str) = nationalities_ids {
                        for nat_id in nat_ids_str.split(';') {
                            let nat_id = nat_id.trim();
                            if nat_id.is_empty() {
                                continue;
                            }
                            if let Some(nat_info) = nat_lookup.get(nat_id) {
                                if let Some(url) = &nat_info.url {
                                    let polities = find_all_polities_by_url_no_year(url);
                                    if !polities.is_empty() {
                                        matched = Some((
                                            polities,
                                            "nationality",
                                            nat_info.name_en.clone(),
                                            nat_id.to_string(),
                                            "url_fallback",
                                            None,
                                        ));
                                        break;
                                    }
                                }
                            }
                        }
                    }

                    // Fallback birthplace URL
                    if matched.is_none() {
                        if let Some(bc_id) = birthcity_id {
                            let bc_id = bc_id.trim();
                            if !bc_id.is_empty() {
                                if let Some(city_info) = city_lookup.get(bc_id) {
                                    if let Some(url) = &city_info.url {
                                        let polities = find_all_polities_by_url_no_year(url);
                                        if !polities.is_empty() {
                                            matched = Some((
                                                polities,
                                                "birthplace",
                                                city_info.name_en.clone(),
                                                bc_id.to_string(),
                                                "url_fallback",
                                                None,
                                            ));
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // Fallback deathplace URL
                    if matched.is_none() {
                        if let Some(dc_id) = deathcity_id {
                            let dc_id = dc_id.trim();
                            if !dc_id.is_empty() {
                                if let Some(city_info) = city_lookup.get(dc_id) {
                                    if let Some(url) = &city_info.url {
                                        let polities = find_all_polities_by_url_no_year(url);
                                        if !polities.is_empty() {
                                            matched = Some((
                                                polities,
                                                "deathplace",
                                                city_info.name_en.clone(),
                                                dc_id.to_string(),
                                                "url_fallback",
                                                None,
                                            ));
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                if let Some((polities, origin, matched_name, matched_wid, method, impact_year)) = matched {
                    // Build semicolon-separated polity_name and polity_id strings
                    let polity_names: String = polities
                        .iter()
                        .map(|(n, _)| n.as_str())
                        .collect::<Vec<_>>()
                        .join(";");
                    let polity_ids: String = polities
                        .iter()
                        .map(|(_, id)| id.to_string())
                        .collect::<Vec<_>>()
                        .join(";");

                    if polities.len() > 1 {
                        cnt_multi_polity += 1;
                    }

                    insert.execute(params![
                        wikidata_id,
                        name_en,
                        polity_names,
                        polity_ids,
                        origin,
                        matched_name,
                        matched_wid,
                        method,
                        impact_year
                    ])?;
                    match method {
                        "polygon" => match origin {
                            "nationality" => cnt_nat_poly += 1,
                            "birthplace" => cnt_birth_poly += 1,
                            "deathplace" => cnt_death_poly += 1,
                            _ => {}
                        },
                        "url" => match origin {
                            "nationality" => cnt_nat_url += 1,
                            "birthplace" => cnt_birth_url += 1,
                            "deathplace" => cnt_death_url += 1,
                            _ => {}
                        },
                        "url_fallback" => cnt_fallback_url += 1,
                        _ => {}
                    }
                    total_inserted += 1;
                } else {
                    cnt_unmatched += 1;
                }
            }
        }
        conn.execute_batch("COMMIT;")?;

        pb.inc(batch.len() as u64);
        offset += batch.len() as i64;

        if offset % 500_000 < BATCH_SIZE as i64 {
            let cnt_poly = cnt_nat_poly + cnt_birth_poly + cnt_death_poly;
            let cnt_url = cnt_nat_url + cnt_birth_url + cnt_death_url;
            log(&format!(
                "[50] Progress: {}/{} | inserted:{} (poly:{} [nat:{},birth:{},death:{}], url:{} [nat:{},birth:{},death:{}], fallback:{}, multi:{}) | unmatched:{}",
                offset, total, total_inserted,
                cnt_poly, cnt_nat_poly, cnt_birth_poly, cnt_death_poly,
                cnt_url, cnt_nat_url, cnt_birth_url, cnt_death_url,
                cnt_fallback_url,
                cnt_multi_polity,
                cnt_unmatched
            ));
        }
    }
    pb.finish();

    log(&format!(
        "[50] Done processing. Total inserted: {}, unmatched: {}, multi-polity: {}",
        total_inserted, cnt_unmatched, cnt_multi_polity
    ));

    // ========================================================
    // PHASE 5: Indexes
    // ========================================================
    log("[50] Creating indexes...");
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_ic_polity ON individuals_cliopatria(polity_name);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_ic_polity_id ON individuals_cliopatria(polity_id);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_ic_origin ON individuals_cliopatria(origin);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_ic_method ON individuals_cliopatria(method);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_ic_matched_wid ON individuals_cliopatria(matched_wikidata_id);")?;

    // ========================================================
    // PHASE 6: Update polities_cliopatria with number_individuals using polity_id
    //   polity_id is now semicolon-separated, so we split and count each ID
    // ========================================================
    log("[50] Updating polities_cliopatria with number_individuals (by polity_id, splitting semicolons)...");

    // Drop old columns and ensure number_individuals exists
    {
        let cols: Vec<String> = {
            let mut stmt = conn.prepare("PRAGMA table_info(polities_cliopatria)")?;
            let mapped = stmt.query_map([], |r| r.get::<_, String>(1))?;
            let result: Vec<String> = mapped.filter_map(|r| r.ok()).collect();
            result
        };

        if cols.contains(&"mixed_count".to_string()) || cols.contains(&"individuals_with_impact_count".to_string()) {
            conn.execute_batch(
                "CREATE TABLE polities_cliopatria_new (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    type TEXT,
                    wikipedia_url TEXT,
                    wikidata_id TEXT,
                    number_individuals INTEGER DEFAULT 0
                );
                INSERT INTO polities_cliopatria_new (id, name, type, wikipedia_url, wikidata_id)
                SELECT id, name, type, wikipedia_url, wikidata_id FROM polities_cliopatria;
                DROP TABLE polities_cliopatria;
                ALTER TABLE polities_cliopatria_new RENAME TO polities_cliopatria;",
            )?;
            log("[50] Rebuilt polities_cliopatria with number_individuals column (removed old count columns)");
        } else if !cols.contains(&"number_individuals".to_string()) {
            conn.execute_batch(
                "ALTER TABLE polities_cliopatria ADD COLUMN number_individuals INTEGER DEFAULT 0;",
            )?;
        }
    }

    // Reset all counts to 0
    conn.execute_batch("UPDATE polities_cliopatria SET number_individuals = 0;")?;

    // Count by splitting semicolon-separated polity_id values
    let mut counts_by_id: HashMap<i64, i64> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT polity_id FROM individuals_cliopatria",
        )?;
        let rows = stmt.query_map([], |r| r.get::<_, String>(0))?;
        for r in rows {
            let pid_str = r?;
            for pid in pid_str.split(';') {
                let pid = pid.trim();
                if let Ok(id) = pid.parse::<i64>() {
                    *counts_by_id.entry(id).or_insert(0) += 1;
                }
            }
        }
    }

    conn.execute_batch("BEGIN TRANSACTION;")?;
    {
        let mut update =
            conn.prepare("UPDATE polities_cliopatria SET number_individuals = ?1 WHERE id = ?2")?;
        for (id, cnt) in &counts_by_id {
            update.execute(params![cnt, id])?;
        }
    }
    conn.execute_batch("COMMIT;")?;

    let polities_with_individuals: usize = counts_by_id.values().filter(|&&c| c > 0).count();
    log(&format!(
        "[50] Updated number_individuals for {} polities",
        polities_with_individuals
    ));

    // ========================================================
    // PHASE 7: Final stats
    // ========================================================
    let final_count: i64 =
        conn.query_row("SELECT COUNT(*) FROM individuals_cliopatria", [], |r| r.get(0))?;

    let cnt_poly = cnt_nat_poly + cnt_birth_poly + cnt_death_poly;
    let cnt_url = cnt_nat_url + cnt_birth_url + cnt_death_url;
    log("[50] === Final Statistics ===");
    log(&format!("[50] Total individuals: {}", total));
    log(&format!("[50] Total in individuals_cliopatria: {}", final_count));
    log(&format!("[50]   via polygon (total): {}", cnt_poly));
    log(&format!("[50]     nationality polygon: {}", cnt_nat_poly));
    log(&format!("[50]     birthplace polygon: {}", cnt_birth_poly));
    log(&format!("[50]     deathplace polygon: {}", cnt_death_poly));
    log(&format!("[50]   via URL (total): {}", cnt_url));
    log(&format!("[50]     url nationality: {}", cnt_nat_url));
    log(&format!("[50]     url birthplace: {}", cnt_birth_url));
    log(&format!("[50]     url deathplace: {}", cnt_death_url));
    log(&format!("[50]   via URL fallback (no year): {}", cnt_fallback_url));
    log(&format!("[50]   Multi-polity individuals: {}", cnt_multi_polity));
    log(&format!("[50] Unmatched: {}", cnt_unmatched));

    // Top 20 polities by number_individuals
    let mut top = conn.prepare(
        "SELECT pc.id, pc.name, pc.number_individuals FROM polities_cliopatria pc ORDER BY pc.number_individuals DESC LIMIT 20",
    )?;
    let rows: Vec<(i64, String, i64)> = top
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[50] Top 20 polities (number_individuals):");
    for (id, name, cnt) in &rows {
        log(&format!("[50]   [id={}] {} -> {}", id, name, cnt));
    }

    // Origin + method breakdown
    let mut breakdown = conn.prepare(
        "SELECT method, origin, COUNT(*) FROM individuals_cliopatria GROUP BY method, origin ORDER BY COUNT(*) DESC",
    )?;
    let rows: Vec<(String, String, i64)> = breakdown
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[50] Method + origin breakdown:");
    for (method, origin, cnt) in &rows {
        log(&format!("[50]   {} / {} -> {}", method, origin, cnt));
    }

    // Show some examples of multi-polity individuals
    {
        let mut stmt = conn.prepare(
            "SELECT wikidata_id, name_en, polity_name, polity_id, method, impact_date
             FROM individuals_cliopatria
             WHERE polity_id LIKE '%;%'
             LIMIT 10",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, Option<String>>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, String>(3)?,
                r.get::<_, String>(4)?,
                r.get::<_, Option<i32>>(5)?,
            ))
        })?;
        log("[50] Sample multi-polity individuals:");
        for r in rows {
            let (wid, name, pnames, pids, method, year) = r?;
            log(&format!(
                "[50]   {} | {} | polities: {} | ids: {} | {} | year={}",
                wid,
                name.unwrap_or_default(),
                pnames,
                pids,
                method,
                year.unwrap_or(0),
            ));
        }
    }

    log("=== Step 50 complete ===");
    Ok(())
}
