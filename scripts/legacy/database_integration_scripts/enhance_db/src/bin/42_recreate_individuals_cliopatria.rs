/// Recreate individuals_cliopatria using wikidata_ids from individuals_keys
/// to avoid city name ambiguity (e.g., Florence USA vs Florence Italy).
///
/// Priority order:
/// 1. Deathplace polygon (with impact_date check)
/// 2. Birthplace polygon (with impact_date check)
/// 3. Nationality polygon (with impact_date check)
/// 4. URL nationality (with impact_date check against polity periods)
/// 5. URL deathcity (with impact_date check against polity periods)
/// 6. URL birthcity (with impact_date check against polity periods)
///
/// New columns vs old: matched_wikidata_id, impact_date
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
    log("=== Step 42: Recreate individuals_cliopatria (wikidata_id-based lookups) ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // ========================================================
    // PHASE 1: Load polity periods with geometries from main DB
    // ========================================================
    log("[42] Loading polity name lookup from polities_cliopatria...");
    let mut polity_id_to_name: HashMap<i64, String> = HashMap::new();
    {
        let mut stmt = conn.prepare("SELECT id, name FROM polities_cliopatria")?;
        let rows = stmt.query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?)))?;
        for r in rows {
            let (id, name) = r?;
            polity_id_to_name.insert(id, name);
        }
    }
    log(&format!("[42] Polity name lookup: {} entries", polity_id_to_name.len()));

    log("[42] Building URL-to-polity lookup from polities_cliopatria...");
    let mut url_to_polity: HashMap<String, (String, i64)> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT id, name, wikipedia_url FROM polities_cliopatria WHERE wikipedia_url IS NOT NULL",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?))
        })?;
        for r in rows {
            let (id, name, url) = r?;
            url_to_polity.entry(url).or_insert((name, id));
        }
    }
    log(&format!("[42] URL-to-polity lookup: {} entries", url_to_polity.len()));

    log("[42] Loading polity periods from cliopatria_polity_periods...");
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
        log(&format!("[42] Loaded {} polity periods ({} skipped)", periods.len(), skipped));
    }

    // ========================================================
    // PHASE 2: Build lookups keyed by wikidata_id
    // ========================================================

    // City lookup: city wikidata_id -> PlaceInfo
    log("[42] Building city lookup (by wikidata_id)...");
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
    log(&format!("[42] City lookup: {} entries", city_lookup.len()));

    // Nationality lookup: nationality wikidata_id -> PlaceInfo
    log("[42] Building nationality lookup (by wikidata_id)...");
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
    log(&format!("[42] Nationality lookup: {} entries", nat_lookup.len()));

    // Impact date lookup: individual wikidata_id -> year
    log("[42] Building impact date lookup...");
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
    log(&format!("[42] Impact date lookup: {} entries", impact_lookup.len()));

    // Polity-id to year-ranges lookup (all periods, not just those with geometry)
    log("[42] Building polity year-range lookup...");
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
    log(&format!("[42] Polity year-range lookup: {} polities", polity_id_to_years.len()));

    // ========================================================
    // PHASE 3: Create individuals_cliopatria table
    // ========================================================
    log("[42] Dropping and recreating individuals_cliopatria table...");
    conn.execute_batch("DROP TABLE IF EXISTS individuals_cliopatria;")?;
    conn.execute_batch(
        "CREATE TABLE individuals_cliopatria (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            polity_name TEXT,
            polity_id INTEGER,
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
    log(&format!("[42] Total individuals to process: {}", total));

    let pb = ProgressBar::new(total as u64);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{msg} [{bar:40}] {pos}/{len} ({eta})")
            .unwrap(),
    );
    pb.set_message("Matching individuals to cliopatria");

    let mut offset: i64 = 0;
    let mut cnt_death_poly = 0u64;
    let mut cnt_birth_poly = 0u64;
    let mut cnt_nat_poly = 0u64;
    let mut cnt_url_nat = 0u64;
    let mut cnt_url_death = 0u64;
    let mut cnt_url_birth = 0u64;
    let mut cnt_unmatched = 0u64;
    let mut total_inserted = 0u64;

    // Helper: find best polity by polygon (smallest area = most specific)
    let find_polity_by_polygon =
        |lon: f64, lat: f64, year: i32| -> Option<(String, i64)> {
            let mut best: Option<(String, i64, f64)> = None;
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
                    match &best {
                        Some((_, _, best_area)) if pp.area >= *best_area => {}
                        _ => {
                            best = Some((pp.polity_name.clone(), pp.polity_id, pp.area));
                        }
                    }
                }
            }
            best.map(|(name, id, _)| (name, id))
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
                // matched = (polity_name, polity_id, origin, matched_name, matched_wikidata_id, method, impact_date)
                let mut matched: Option<(String, i64, &str, String, String, &str, Option<i32>)> = None;

                // === POLYGON MATCHING FIRST (requires impact_date) ===
                if let Some(&year) = impact_lookup.get(wikidata_id.as_str()) {
                    // Priority 1: Deathplace polygon
                    if matched.is_none() {
                        if let Some(dc_id) = deathcity_id {
                            let dc_id = dc_id.trim();
                            if !dc_id.is_empty() {
                                if let Some(city_info) = city_lookup.get(dc_id) {
                                    if let Some((lon, lat)) = city_info.coords {
                                        if let Some((pname, pid)) = find_polity_by_polygon(lon, lat, year) {
                                            matched = Some((
                                                pname,
                                                pid,
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

                    // Priority 2: Birthplace polygon
                    if matched.is_none() {
                        if let Some(bc_id) = birthcity_id {
                            let bc_id = bc_id.trim();
                            if !bc_id.is_empty() {
                                if let Some(city_info) = city_lookup.get(bc_id) {
                                    if let Some((lon, lat)) = city_info.coords {
                                        if let Some((pname, pid)) = find_polity_by_polygon(lon, lat, year) {
                                            matched = Some((
                                                pname,
                                                pid,
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

                    // Priority 3: Nationality polygon
                    if matched.is_none() {
                        if let Some(nat_ids_str) = nationalities_ids {
                            for nat_id in nat_ids_str.split(';') {
                                let nat_id = nat_id.trim();
                                if nat_id.is_empty() {
                                    continue;
                                }
                                if let Some(nat_info) = nat_lookup.get(nat_id) {
                                    if let Some((lon, lat)) = nat_info.coords {
                                        if let Some((pname, pid)) = find_polity_by_polygon(lon, lat, year) {
                                            matched = Some((
                                                pname,
                                                pid,
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
                }

                // === URL FALLBACK (requires impact_date within polity period) ===

                // Priority 4: URL nationality
                if matched.is_none() {
                    if let Some(&year) = impact_lookup.get(wikidata_id.as_str()) {
                        if let Some(nat_ids_str) = nationalities_ids {
                            for nat_id in nat_ids_str.split(';') {
                                let nat_id = nat_id.trim();
                                if nat_id.is_empty() {
                                    continue;
                                }
                                if let Some(nat_info) = nat_lookup.get(nat_id) {
                                    if let Some(url) = &nat_info.url {
                                        if let Some((polity_name, polity_id)) = url_to_polity.get(url.as_str()) {
                                            if polity_id_to_years.get(polity_id).map_or(false, |yrs| {
                                                yrs.iter().any(|(from, to)| year >= *from && year <= *to)
                                            }) {
                                                matched = Some((
                                                    polity_name.clone(),
                                                    *polity_id,
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
                    }
                }

                // Priority 5: URL deathcity
                if matched.is_none() {
                    if let Some(&year) = impact_lookup.get(wikidata_id.as_str()) {
                        if let Some(dc_id) = deathcity_id {
                            let dc_id = dc_id.trim();
                            if !dc_id.is_empty() {
                                if let Some(city_info) = city_lookup.get(dc_id) {
                                    if let Some(url) = &city_info.url {
                                        if let Some((polity_name, polity_id)) = url_to_polity.get(url.as_str()) {
                                            if polity_id_to_years.get(polity_id).map_or(false, |yrs| {
                                                yrs.iter().any(|(from, to)| year >= *from && year <= *to)
                                            }) {
                                                matched = Some((
                                                    polity_name.clone(),
                                                    *polity_id,
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
                }

                // Priority 6: URL birthcity
                if matched.is_none() {
                    if let Some(&year) = impact_lookup.get(wikidata_id.as_str()) {
                        if let Some(bc_id) = birthcity_id {
                            let bc_id = bc_id.trim();
                            if !bc_id.is_empty() {
                                if let Some(city_info) = city_lookup.get(bc_id) {
                                    if let Some(url) = &city_info.url {
                                        if let Some((polity_name, polity_id)) = url_to_polity.get(url.as_str()) {
                                            if polity_id_to_years.get(polity_id).map_or(false, |yrs| {
                                                yrs.iter().any(|(from, to)| year >= *from && year <= *to)
                                            }) {
                                                matched = Some((
                                                    polity_name.clone(),
                                                    *polity_id,
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
                    }
                }

                if let Some((polity_name, polity_id, origin, matched_name, matched_wid, method, impact_year)) = matched {
                    insert.execute(params![
                        wikidata_id,
                        name_en,
                        polity_name,
                        polity_id,
                        origin,
                        matched_name,
                        matched_wid,
                        method,
                        impact_year
                    ])?;
                    match (method, origin) {
                        ("polygon", "deathplace") => cnt_death_poly += 1,
                        ("polygon", "birthplace") => cnt_birth_poly += 1,
                        ("polygon", "nationality") => cnt_nat_poly += 1,
                        ("url", "nationality") => cnt_url_nat += 1,
                        ("url", "deathplace") => cnt_url_death += 1,
                        ("url", "birthplace") => cnt_url_birth += 1,
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
            let cnt_poly = cnt_death_poly + cnt_birth_poly + cnt_nat_poly;
            let cnt_url = cnt_url_nat + cnt_url_death + cnt_url_birth;
            log(&format!(
                "[42] Progress: {}/{} | inserted:{} (poly:{} [death:{},birth:{},nat:{}], url:{} [nat:{},death:{},birth:{}]) | unmatched:{}",
                offset, total, total_inserted,
                cnt_poly, cnt_death_poly, cnt_birth_poly, cnt_nat_poly,
                cnt_url, cnt_url_nat, cnt_url_death, cnt_url_birth,
                cnt_unmatched
            ));
        }
    }
    pb.finish();

    log(&format!(
        "[42] Done processing. Total inserted: {}, unmatched: {}",
        total_inserted, cnt_unmatched
    ));

    // ========================================================
    // PHASE 5: Indexes
    // ========================================================
    log("[42] Creating indexes...");
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_ic_polity ON individuals_cliopatria(polity_name);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_ic_polity_id ON individuals_cliopatria(polity_id);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_ic_origin ON individuals_cliopatria(origin);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_ic_method ON individuals_cliopatria(method);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_ic_matched_wid ON individuals_cliopatria(matched_wikidata_id);")?;

    // ========================================================
    // PHASE 6: Update polities_cliopatria with mixed_count
    // ========================================================
    log("[42] Updating polities_cliopatria with mixed_count...");

    let has_col: bool = {
        let mut stmt = conn.prepare("PRAGMA table_info(polities_cliopatria)")?;
        let cols: Vec<String> = stmt
            .query_map([], |r| r.get::<_, String>(1))?
            .filter_map(|r| r.ok())
            .collect();
        cols.contains(&"mixed_count".to_string())
    };
    if !has_col {
        conn.execute_batch(
            "ALTER TABLE polities_cliopatria ADD COLUMN mixed_count INTEGER DEFAULT 0;",
        )?;
    } else {
        conn.execute_batch("UPDATE polities_cliopatria SET mixed_count = 0;")?;
    }

    let mut counts: HashMap<String, i64> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT polity_name, COUNT(*) FROM individuals_cliopatria GROUP BY polity_name",
        )?;
        let rows = stmt.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?)))?;
        for r in rows {
            let (name, cnt) = r?;
            counts.insert(name, cnt);
        }
    }

    conn.execute_batch("BEGIN TRANSACTION;")?;
    {
        let mut update =
            conn.prepare("UPDATE polities_cliopatria SET mixed_count = ?1 WHERE name = ?2")?;
        for (name, cnt) in &counts {
            update.execute(params![cnt, name])?;
        }
    }
    conn.execute_batch("COMMIT;")?;

    // ========================================================
    // PHASE 7: Final stats
    // ========================================================
    let final_count: i64 =
        conn.query_row("SELECT COUNT(*) FROM individuals_cliopatria", [], |r| r.get(0))?;

    let cnt_poly = cnt_death_poly + cnt_birth_poly + cnt_nat_poly;
    let cnt_url = cnt_url_nat + cnt_url_death + cnt_url_birth;
    log("[42] === Final Statistics ===");
    log(&format!("[42] Total individuals: {}", total));
    log(&format!("[42] Total in individuals_cliopatria: {}", final_count));
    log(&format!("[42]   via polygon (total): {}", cnt_poly));
    log(&format!("[42]     deathplace polygon: {}", cnt_death_poly));
    log(&format!("[42]     birthplace polygon: {}", cnt_birth_poly));
    log(&format!("[42]     nationality polygon: {}", cnt_nat_poly));
    log(&format!("[42]   via URL (total): {}", cnt_url));
    log(&format!("[42]     url nationality: {}", cnt_url_nat));
    log(&format!("[42]     url deathplace: {}", cnt_url_death));
    log(&format!("[42]     url birthplace: {}", cnt_url_birth));
    log(&format!("[42] Unmatched: {}", cnt_unmatched));

    // Top 20 polities
    let mut top = conn.prepare(
        "SELECT name, mixed_count FROM polities_cliopatria ORDER BY mixed_count DESC LIMIT 20",
    )?;
    let rows: Vec<(String, i64)> = top
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[42] Top 20 polities (mixed count):");
    for (name, cnt) in &rows {
        log(&format!("[42]   {} -> {}", name, cnt));
    }

    // Origin + method breakdown
    let mut breakdown = conn.prepare(
        "SELECT method, origin, COUNT(*) FROM individuals_cliopatria GROUP BY method, origin ORDER BY COUNT(*) DESC",
    )?;
    let rows: Vec<(String, String, i64)> = breakdown
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[42] Method + origin breakdown:");
    for (method, origin, cnt) in &rows {
        log(&format!("[42]   {} / {} -> {}", method, origin, cnt));
    }

    log("=== Step 42 complete ===");
    Ok(())
}
