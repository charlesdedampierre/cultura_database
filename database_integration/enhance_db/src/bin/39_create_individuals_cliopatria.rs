/// Create individuals_cliopatria table combining polygon and URL matching.
/// Priority order:
/// 1. Deathplace polygon (with impact_date check)
/// 2. Birthplace polygon (with impact_date check)
/// 3. Nationality polygon (with impact_date check)
/// 4. URL nationality
/// 5. URL deathcity
/// 6. URL birthcity
/// Columns: wikidata_id, name_en, polity_name, polity_id, origin, matched_name, method
use anyhow::Result;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection};
use std::collections::HashMap;
use std::fs;
use std::io::Write;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const CLIO_DB_PATH: &str = "cliopatria_data/processing/data/cliopatria.db";
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

fn strip_parens(name: &str) -> String {
    let trimmed = name.trim();
    if trimmed.starts_with('(') && trimmed.ends_with(')') {
        trimmed[1..trimmed.len() - 1].to_string()
    } else {
        trimmed.to_string()
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
    bbox: BBox,
    geometry: serde_json::Value,
}

fn main() -> Result<()> {
    let _ = fs::remove_file(TASK_LOG);
    log("=== Step 39: Create individuals_cliopatria (polygon-first + URL fallback) ===");

    // ========================================================
    // PHASE 1: Load polity periods with geometries
    // ========================================================
    log("[39] Loading polity periods from Cliopatria DB...");
    let clio_conn = Connection::open(CLIO_DB_PATH)?;

    let mut polity_id_to_name: HashMap<i64, String> = HashMap::new();
    {
        let mut stmt = clio_conn.prepare("SELECT id, name FROM polities")?;
        let rows = stmt.query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?)))?;
        for r in rows {
            let (id, name) = r?;
            polity_id_to_name.insert(id, strip_parens(&name));
        }
    }

    let mut url_to_polity: HashMap<String, (String, i64)> = HashMap::new();
    {
        let mut stmt = clio_conn.prepare(
            "SELECT id, name, wikipedia_url FROM polities WHERE wikipedia_url IS NOT NULL",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?))
        })?;
        for r in rows {
            let (id, name, url) = r?;
            url_to_polity.entry(url).or_insert((strip_parens(&name), id));
        }
    }
    log(&format!("[39] URL-to-polity lookup: {} entries", url_to_polity.len()));

    let mut periods: Vec<PolityPeriod> = Vec::new();
    {
        let mut stmt = clio_conn.prepare(
            "SELECT polity_id, polity_name, from_year, to_year, geometry FROM polity_periods WHERE geometry IS NOT NULL",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, i32>(2)?,
                r.get::<_, i32>(3)?,
                r.get::<_, String>(4)?,
            ))
        })?;
        let mut skipped = 0;
        for r in rows {
            let (polity_id, polity_name, from_year, to_year, geom_str) = r?;
            if let Ok(geom_json) = serde_json::from_str::<serde_json::Value>(&geom_str) {
                if let Some(bbox) = compute_bbox(&geom_json) {
                    let clean_name = polity_id_to_name
                        .get(&polity_id)
                        .cloned()
                        .unwrap_or_else(|| strip_parens(&polity_name));
                    periods.push(PolityPeriod {
                        polity_id,
                        polity_name: clean_name,
                        from_year,
                        to_year,
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
        log(&format!("[39] Loaded {} polity periods ({} skipped)", periods.len(), skipped));
    }
    drop(clio_conn);

    // ========================================================
    // PHASE 2: Build lookups from humans_clean DB
    // ========================================================
    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    log("[39] Building nationality URL lookup...");
    let mut nat_url_lookup: HashMap<String, String> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT name_en, en_wikipedia_url FROM nationalities WHERE en_wikipedia_url IS NOT NULL",
        )?;
        let rows = stmt.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))?;
        for r in rows {
            let (name, url) = r?;
            nat_url_lookup.insert(name, url);
        }
    }
    log(&format!("[39] Nationality URL lookup: {} entries", nat_url_lookup.len()));

    log("[39] Building city URL lookup...");
    let mut city_url_lookup: HashMap<String, String> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT name_en, en_wikipedia_url_original_country_name FROM cities WHERE en_wikipedia_url_original_country_name IS NOT NULL",
        )?;
        let rows = stmt.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))?;
        for r in rows {
            let (name, url) = r?;
            city_url_lookup.entry(name).or_insert(url);
        }
    }
    log(&format!("[39] City URL lookup: {} entries", city_url_lookup.len()));

    log("[39] Building nationality location lookup...");
    let mut nat_loc_lookup: HashMap<String, (f64, f64)> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT name_en, lon, lat FROM nationalities WHERE lat IS NOT NULL AND lon IS NOT NULL",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, f64>(1)?, r.get::<_, f64>(2)?))
        })?;
        for r in rows {
            let (name, lon, lat) = r?;
            nat_loc_lookup.insert(name, (lon, lat));
        }
    }
    log(&format!("[39] Nationality location lookup: {} entries", nat_loc_lookup.len()));

    log("[39] Building city location lookup...");
    let mut city_loc_lookup: HashMap<String, (f64, f64)> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT name_en, lon, lat FROM cities WHERE lat IS NOT NULL AND lon IS NOT NULL",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, f64>(1)?, r.get::<_, f64>(2)?))
        })?;
        for r in rows {
            let (name, lon, lat) = r?;
            city_loc_lookup.entry(name).or_insert((lon, lat));
        }
    }
    log(&format!("[39] City location lookup: {} entries", city_loc_lookup.len()));

    log("[39] Building impact date lookup...");
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
    log(&format!("[39] Impact date lookup: {} entries", impact_lookup.len()));

    // ========================================================
    // PHASE 3: Create individuals_cliopatria table
    // ========================================================
    log("[39] Creating individuals_cliopatria table...");
    conn.execute_batch("DROP TABLE IF EXISTS individuals_cliopatria;")?;
    conn.execute_batch(
        "CREATE TABLE individuals_cliopatria (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            polity_name TEXT,
            polity_id INTEGER,
            origin TEXT,
            matched_name TEXT,
            method TEXT
        );",
    )?;

    // ========================================================
    // PHASE 4: Process all individuals
    // ========================================================
    let total: i64 = conn.query_row("SELECT COUNT(*) FROM individuals", [], |r| r.get(0))?;
    log(&format!("[39] Total individuals to process: {}", total));

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
                    let area = (pp.bbox.max_lon - pp.bbox.min_lon)
                        * (pp.bbox.max_lat - pp.bbox.min_lat);
                    match &best {
                        Some((_, _, best_area)) if area >= *best_area => {}
                        _ => {
                            best = Some((pp.polity_name.clone(), pp.polity_id, area));
                        }
                    }
                }
            }
            best.map(|(name, id, _)| (name, id))
        };

    loop {
        let mut batch: Vec<(
            String,
            Option<String>,
            Option<String>,
            Option<String>,
            Option<String>,
        )> = Vec::with_capacity(BATCH_SIZE);
        {
            let mut stmt = conn.prepare_cached(
                "SELECT wikidata_id, name_en, nationalities_en, deathcity_en, birthcity_en
                 FROM individuals
                 ORDER BY rowid
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
                 (wikidata_id, name_en, polity_name, polity_id, origin, matched_name, method)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            )?;

            for (wikidata_id, name_en, nationalities_en, deathcity_en, birthcity_en) in &batch {
                // matched = (polity_name, polity_id, origin, matched_name, method)
                let mut matched: Option<(String, i64, &str, String, &str)> = None;

                // === POLYGON MATCHING FIRST (requires impact_date) ===
                if let Some(&year) = impact_lookup.get(wikidata_id.as_str()) {
                    // Priority 1: Deathplace polygon
                    if matched.is_none() {
                        if let Some(city) = deathcity_en {
                            let city = city.trim();
                            if let Some(&(lon, lat)) = city_loc_lookup.get(city) {
                                if let Some((pname, pid)) = find_polity_by_polygon(lon, lat, year)
                                {
                                    matched = Some((
                                        pname,
                                        pid,
                                        "deathplace",
                                        city.to_string(),
                                        "polygon",
                                    ));
                                }
                            }
                        }
                    }

                    // Priority 2: Birthplace polygon
                    if matched.is_none() {
                        if let Some(city) = birthcity_en {
                            let city = city.trim();
                            if let Some(&(lon, lat)) = city_loc_lookup.get(city) {
                                if let Some((pname, pid)) = find_polity_by_polygon(lon, lat, year)
                                {
                                    matched = Some((
                                        pname,
                                        pid,
                                        "birthplace",
                                        city.to_string(),
                                        "polygon",
                                    ));
                                }
                            }
                        }
                    }

                    // Priority 3: Nationality polygon
                    if matched.is_none() {
                        if let Some(nats) = nationalities_en {
                            for nat_name in nats.split("; ") {
                                let nat_name = nat_name.trim();
                                if let Some(&(lon, lat)) = nat_loc_lookup.get(nat_name) {
                                    if let Some((pname, pid)) =
                                        find_polity_by_polygon(lon, lat, year)
                                    {
                                        matched = Some((
                                            pname,
                                            pid,
                                            "nationality",
                                            nat_name.to_string(),
                                            "polygon",
                                        ));
                                        break;
                                    }
                                }
                            }
                        }
                    }
                }

                // === URL FALLBACK ===

                // Priority 4: URL nationality
                if matched.is_none() {
                    if let Some(nats) = nationalities_en {
                        for nat_name in nats.split("; ") {
                            let nat_name = nat_name.trim();
                            if let Some(url) = nat_url_lookup.get(nat_name) {
                                if let Some((polity_name, polity_id)) = url_to_polity.get(url) {
                                    matched = Some((
                                        polity_name.clone(),
                                        *polity_id,
                                        "nationality",
                                        nat_name.to_string(),
                                        "url",
                                    ));
                                    break;
                                }
                            }
                        }
                    }
                }

                // Priority 5: URL deathcity
                if matched.is_none() {
                    if let Some(city) = deathcity_en {
                        let city = city.trim();
                        if let Some(url) = city_url_lookup.get(city) {
                            if let Some((polity_name, polity_id)) = url_to_polity.get(url) {
                                matched = Some((
                                    polity_name.clone(),
                                    *polity_id,
                                    "deathplace",
                                    city.to_string(),
                                    "url",
                                ));
                            }
                        }
                    }
                }

                // Priority 6: URL birthcity
                if matched.is_none() {
                    if let Some(city) = birthcity_en {
                        let city = city.trim();
                        if let Some(url) = city_url_lookup.get(city) {
                            if let Some((polity_name, polity_id)) = url_to_polity.get(url) {
                                matched = Some((
                                    polity_name.clone(),
                                    *polity_id,
                                    "birthplace",
                                    city.to_string(),
                                    "url",
                                ));
                            }
                        }
                    }
                }

                if let Some((polity_name, polity_id, origin, matched_name, method)) = matched {
                    insert.execute(params![
                        wikidata_id,
                        name_en,
                        polity_name,
                        polity_id,
                        origin,
                        matched_name,
                        method
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
                "[39] Progress: {}/{} | inserted:{} (poly:{} [death:{},birth:{},nat:{}], url:{} [nat:{},death:{},birth:{}]) | unmatched:{}",
                offset, total, total_inserted,
                cnt_poly, cnt_death_poly, cnt_birth_poly, cnt_nat_poly,
                cnt_url, cnt_url_nat, cnt_url_death, cnt_url_birth,
                cnt_unmatched
            ));
        }
    }
    pb.finish();

    log(&format!(
        "[39] Done processing. Total inserted: {}, unmatched: {}",
        total_inserted, cnt_unmatched
    ));

    // ========================================================
    // PHASE 5: Indexes
    // ========================================================
    log("[39] Creating indexes...");
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_ic_polity ON individuals_cliopatria(polity_name);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_ic_polity_id ON individuals_cliopatria(polity_id);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_ic_origin ON individuals_cliopatria(origin);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_ic_method ON individuals_cliopatria(method);")?;

    // ========================================================
    // PHASE 6: Update polities_cliopatria with mixed_count
    // ========================================================
    log("[39] Updating polities_cliopatria with mixed_count...");

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
    log("[39] === Final Statistics ===");
    log(&format!("[39] Total individuals: {}", total));
    log(&format!("[39] Total in individuals_cliopatria: {}", final_count));
    log(&format!("[39]   via polygon (total): {}", cnt_poly));
    log(&format!("[39]     deathplace polygon: {}", cnt_death_poly));
    log(&format!("[39]     birthplace polygon: {}", cnt_birth_poly));
    log(&format!("[39]     nationality polygon: {}", cnt_nat_poly));
    log(&format!("[39]   via URL (total): {}", cnt_url));
    log(&format!("[39]     url nationality: {}", cnt_url_nat));
    log(&format!("[39]     url deathplace: {}", cnt_url_death));
    log(&format!("[39]     url birthplace: {}", cnt_url_birth));
    log(&format!("[39] Unmatched: {}", cnt_unmatched));

    // Top 20 polities
    let mut top = conn.prepare(
        "SELECT name, mixed_count FROM polities_cliopatria ORDER BY mixed_count DESC LIMIT 20",
    )?;
    let rows: Vec<(String, i64)> = top
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[39] Top 20 polities (mixed count):");
    for (name, cnt) in &rows {
        log(&format!("[39]   {} -> {}", name, cnt));
    }

    // Origin + method breakdown
    let mut breakdown = conn.prepare(
        "SELECT method, origin, COUNT(*) FROM individuals_cliopatria GROUP BY method, origin ORDER BY COUNT(*) DESC",
    )?;
    let rows: Vec<(String, String, i64)> = breakdown
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[39] Method + origin breakdown:");
    for (method, origin, cnt) in &rows {
        log(&format!("[39]   {} / {} -> {}", method, origin, cnt));
    }

    log("=== Step 39 complete ===");
    Ok(())
}
