/// Rebuild the corrupted individuals_countries table from scratch.
/// Associates each individual with a modern country based on:
/// 1. nationality (first priority)
/// 2. deathplace (second priority)
/// 3. birthplace (third priority)
/// Then applies region/macro_region from the regions table using impact_date.
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
        Some(-(year as i32))
    } else {
        let year_str = date_str.split('-').next()?;
        let year: i32 = year_str.parse().ok()?;
        Some(year)
    }
}

#[derive(Clone)]
struct RegionEntry {
    macro_region: String,
    region: String,
    start_year: i32,
    end_year: Option<i32>,
}

fn main() -> Result<()> {
    // Reset task.log
    let _ = fs::remove_file(TASK_LOG);
    log("=== Step 31: Rebuild individuals_countries (corrupted) ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // ========================================================
    // PHASE 1: Build lookups
    // ========================================================

    // Build nationality name -> (iso_country_name, iso_a3_code) lookup
    log("[31] Building nationality lookup...");
    let mut nat_lookup: HashMap<String, (String, String)> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT name_en, iso_country_name, iso_a3_code FROM nationalities WHERE iso_country_name IS NOT NULL AND iso_a3_code IS NOT NULL"
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
            ))
        })?;
        for r in rows {
            let (name, country, iso) = r?;
            nat_lookup.insert(name, (country, iso));
        }
    }
    log(&format!("[31] Nationality lookup: {} entries", nat_lookup.len()));

    // Build city name -> (iso_country_name, iso_a3_code) lookup
    log("[31] Building city lookup...");
    let mut city_lookup: HashMap<String, (String, String)> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT name_en, iso_country_name, iso_a3_code FROM cities WHERE iso_country_name IS NOT NULL AND iso_a3_code IS NOT NULL"
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
            ))
        })?;
        for r in rows {
            let (name, country, iso) = r?;
            city_lookup.entry(name).or_insert((country, iso));
        }
    }
    log(&format!("[31] City lookup: {} entries", city_lookup.len()));

    // Build region lookup: iso_a3 -> Vec<RegionEntry>
    log("[31] Building region lookup...");
    let mut region_lookup: HashMap<String, Vec<RegionEntry>> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT macro_region, region, iso_a3, start_year, end_year FROM regions",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, i32>(3)?,
                r.get::<_, Option<i32>>(4)?,
            ))
        })?;
        for r in rows {
            let (macro_region, region, iso_a3, start_year, end_year) = r?;
            region_lookup
                .entry(iso_a3)
                .or_default()
                .push(RegionEntry {
                    macro_region,
                    region,
                    start_year,
                    end_year,
                });
        }
    }
    log(&format!("[31] Region lookup: {} ISO codes", region_lookup.len()));

    // Build impact_date lookup: wikidata_id -> year
    log("[31] Building impact_date lookup...");
    let mut impact_lookup: HashMap<String, i32> = HashMap::new();
    {
        let mut stmt =
            conn.prepare("SELECT wikidata_id, impact_date FROM individuals_impact_date")?;
        let rows = stmt.query_map([], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
        })?;
        for r in rows {
            let (wid, date_str) = r?;
            if let Some(year) = parse_year(&date_str) {
                impact_lookup.insert(wid, year);
            }
        }
    }
    log(&format!("[31] Impact date lookup: {} entries", impact_lookup.len()));

    // ========================================================
    // PHASE 2: Drop and recreate individuals_countries table
    // ========================================================
    log("[31] Creating fresh individuals_countries table...");
    conn.execute_batch("DROP TABLE IF EXISTS individuals_countries;")?;
    conn.execute_batch(
        "CREATE TABLE individuals_countries (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            iso_country_name TEXT,
            iso_a3_code TEXT,
            origins TEXT,
            region TEXT,
            macro_region TEXT
        );"
    )?;
    log("[31] Created fresh individuals_countries table");

    // ========================================================
    // PHASE 3: Rebuild from individuals table
    // ========================================================
    let total: i64 = conn.query_row("SELECT COUNT(*) FROM individuals", [], |r| r.get(0))?;
    log(&format!("[31] Total individuals to process: {}", total));

    let pb = ProgressBar::new(total as u64);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{msg} [{bar:40}] {pos}/{len} ({eta})")
            .unwrap(),
    );
    pb.set_message("Rebuilding individuals_countries");

    let mut offset: i64 = 0;
    let mut matched_nationality = 0u64;
    let mut matched_death = 0u64;
    let mut matched_birth = 0u64;
    let mut unmatched = 0u64;
    let mut total_inserted = 0u64;
    let mut with_region = 0u64;

    loop {
        let mut batch: Vec<(String, Option<String>, Option<String>, Option<String>, Option<String>)> =
            Vec::with_capacity(BATCH_SIZE);
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
                "INSERT OR IGNORE INTO individuals_countries (wikidata_id, name_en, iso_country_name, iso_a3_code, origins, region, macro_region)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            )?;

            for (wikidata_id, name_en, nationalities_en, deathcity_en, birthcity_en) in &batch {
                let mut found_country: Option<(String, String, &str)> = None;

                // Priority 1: nationality
                if let Some(nats) = nationalities_en {
                    for nat_name in nats.split("; ") {
                        let nat_name = nat_name.trim();
                        if let Some((country, iso)) = nat_lookup.get(nat_name) {
                            found_country = Some((country.clone(), iso.clone(), "nationality"));
                            break;
                        }
                    }
                }

                // Priority 2: deathplace
                if found_country.is_none() {
                    if let Some(city) = deathcity_en {
                        let city = city.trim();
                        if let Some((country, iso)) = city_lookup.get(city) {
                            found_country = Some((country.clone(), iso.clone(), "deathplace"));
                        }
                    }
                }

                // Priority 3: birthplace
                if found_country.is_none() {
                    if let Some(city) = birthcity_en {
                        let city = city.trim();
                        if let Some((country, iso)) = city_lookup.get(city) {
                            found_country = Some((country.clone(), iso.clone(), "birthplace"));
                        }
                    }
                }

                if let Some((country, iso, origin)) = found_country {
                    // Resolve region/macro_region based on impact_date
                    let mut region_str: Option<String> = None;
                    let mut macro_str: Option<String> = None;

                    if let Some(&year) = impact_lookup.get(wikidata_id.as_str()) {
                        if let Some(entries) = region_lookup.get(iso.as_str()) {
                            let mut regions: Vec<&str> = Vec::new();
                            let mut macro_regions: Vec<&str> = Vec::new();

                            for entry in entries {
                                let in_range = year >= entry.start_year
                                    && match entry.end_year {
                                        Some(end) => year <= end,
                                        None => true,
                                    };
                                if in_range {
                                    if !regions.contains(&entry.region.as_str()) {
                                        regions.push(&entry.region);
                                    }
                                    if !macro_regions.contains(&entry.macro_region.as_str()) {
                                        macro_regions.push(&entry.macro_region);
                                    }
                                }
                            }

                            if !regions.is_empty() {
                                region_str = Some(regions.join("; "));
                                macro_str = Some(macro_regions.join("; "));
                                with_region += 1;
                            }
                        }
                    }

                    insert.execute(params![
                        wikidata_id,
                        name_en,
                        country,
                        iso,
                        origin,
                        region_str,
                        macro_str
                    ])?;

                    match origin {
                        "nationality" => matched_nationality += 1,
                        "deathplace" => matched_death += 1,
                        "birthplace" => matched_birth += 1,
                        _ => {}
                    }
                    total_inserted += 1;
                } else {
                    unmatched += 1;
                }
            }
        }
        conn.execute_batch("COMMIT;")?;

        pb.inc(batch.len() as u64);
        offset += batch.len() as i64;

        if offset % 500_000 < BATCH_SIZE as i64 {
            log(&format!(
                "[31] Progress: {}/{} processed, {} inserted (nat:{}, death:{}, birth:{}), {} with region, {} unmatched",
                offset, total, total_inserted, matched_nationality, matched_death, matched_birth, with_region, unmatched
            ));
        }
    }
    pb.finish();

    // ========================================================
    // PHASE 4: Create indexes
    // ========================================================
    log("[31] Creating indexes...");
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_indcountries_country ON individuals_countries(iso_country_name);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_indcountries_iso ON individuals_countries(iso_a3_code);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_indcountries_origins ON individuals_countries(origins);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_indcountries_region ON individuals_countries(region);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_indcountries_macro_region ON individuals_countries(macro_region);")?;

    // ========================================================
    // PHASE 5: Final stats
    // ========================================================
    let final_count: i64 = conn.query_row("SELECT COUNT(*) FROM individuals_countries", [], |r| r.get(0))?;
    let with_region_final: i64 = conn.query_row("SELECT COUNT(*) FROM individuals_countries WHERE region IS NOT NULL", [], |r| r.get(0))?;

    log("[31] === Final Statistics ===");
    log(&format!("[31] Total individuals: {}", total));
    log(&format!("[31] Total in individuals_countries: {}", final_count));
    log(&format!("[31]   via nationality: {}", matched_nationality));
    log(&format!("[31]   via deathplace: {}", matched_death));
    log(&format!("[31]   via birthplace: {}", matched_birth));
    log(&format!("[31] With region: {}", with_region_final));
    log(&format!("[31] Without region: {}", final_count - with_region_final));
    log(&format!("[31] Unmatched (no country): {}", unmatched));

    // Top 15 countries
    let mut top = conn.prepare(
        "SELECT iso_country_name, iso_a3_code, COUNT(*) as cnt FROM individuals_countries GROUP BY iso_country_name ORDER BY cnt DESC LIMIT 15",
    )?;
    let rows: Vec<(String, String, i64)> = top
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[31] Top 15 countries:");
    for (name, iso, cnt) in &rows {
        log(&format!("[31]   {} ({}) -> {}", name, iso, cnt));
    }

    // Top macro_regions
    let mut top_mr = conn.prepare(
        "SELECT macro_region, COUNT(*) as cnt FROM individuals_countries WHERE macro_region IS NOT NULL GROUP BY macro_region ORDER BY cnt DESC",
    )?;
    let rows: Vec<(String, i64)> = top_mr
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[31] Macro regions:");
    for (mr, cnt) in &rows {
        log(&format!("[31]   {} -> {}", mr, cnt));
    }

    // Integrity check on the new table
    log("[31] Running integrity check on individuals_countries...");
    let integrity: String = conn.query_row(
        "PRAGMA integrity_check(individuals_countries)",
        [],
        |r| r.get(0),
    )?;
    log(&format!("[31] Integrity: {}", integrity));

    log("=== Step 31 complete ===");
    Ok(())
}
