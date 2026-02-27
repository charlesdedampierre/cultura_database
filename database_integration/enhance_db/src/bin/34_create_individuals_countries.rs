/// Create individuals_countries table from scratch.
/// Associates each individual with a modern country based on:
/// 1. nationality (first priority)
/// 2. deathplace (second priority)
/// 3. birthplace (third priority)
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

fn main() -> Result<()> {
    // Reset task.log
    let _ = fs::remove_file(TASK_LOG);
    log("=== Step 34: Create individuals_countries ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // ========================================================
    // PHASE 1: Build lookups
    // ========================================================

    // Build nationality name -> (iso_country_name, iso_a3_code) lookup
    log("[34] Building nationality lookup...");
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
    log(&format!("[34] Nationality lookup: {} entries", nat_lookup.len()));

    // Build city name -> (iso_country_name, iso_a3_code) lookup
    log("[34] Building city lookup...");
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
    log(&format!("[34] City lookup: {} entries", city_lookup.len()));

    // ========================================================
    // PHASE 2: Drop and recreate individuals_countries table
    // ========================================================
    log("[34] Creating fresh individuals_countries table...");
    conn.execute_batch("DROP TABLE IF EXISTS individuals_countries;")?;
    conn.execute_batch(
        "CREATE TABLE individuals_countries (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            iso_country_name TEXT,
            iso_a3_code TEXT,
            origins TEXT
        );"
    )?;
    log("[34] Created fresh individuals_countries table");

    // ========================================================
    // PHASE 3: Populate from individuals table
    // ========================================================
    let total: i64 = conn.query_row("SELECT COUNT(*) FROM individuals", [], |r| r.get(0))?;
    log(&format!("[34] Total individuals to process: {}", total));

    let pb = ProgressBar::new(total as u64);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{msg} [{bar:40}] {pos}/{len} ({eta})")
            .unwrap(),
    );
    pb.set_message("Creating individuals_countries");

    let mut offset: i64 = 0;
    let mut matched_nationality = 0u64;
    let mut matched_death = 0u64;
    let mut matched_birth = 0u64;
    let mut unmatched = 0u64;
    let mut total_inserted = 0u64;

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
                "INSERT OR IGNORE INTO individuals_countries (wikidata_id, name_en, iso_country_name, iso_a3_code, origins)
                 VALUES (?1, ?2, ?3, ?4, ?5)",
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
                    insert.execute(params![
                        wikidata_id,
                        name_en,
                        country,
                        iso,
                        origin,
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
                "[34] Progress: {}/{} processed, {} inserted (nat:{}, death:{}, birth:{}), {} unmatched",
                offset, total, total_inserted, matched_nationality, matched_death, matched_birth, unmatched
            ));
        }
    }
    pb.finish();

    // ========================================================
    // PHASE 4: Create indexes
    // ========================================================
    log("[34] Creating indexes...");
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_indcountries_country ON individuals_countries(iso_country_name);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_indcountries_iso ON individuals_countries(iso_a3_code);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_indcountries_origins ON individuals_countries(origins);")?;

    // ========================================================
    // PHASE 5: Final stats
    // ========================================================
    let final_count: i64 = conn.query_row("SELECT COUNT(*) FROM individuals_countries", [], |r| r.get(0))?;

    log("[34] === Final Statistics ===");
    log(&format!("[34] Total individuals: {}", total));
    log(&format!("[34] Total in individuals_countries: {}", final_count));
    log(&format!("[34]   via nationality: {}", matched_nationality));
    log(&format!("[34]   via deathplace: {}", matched_death));
    log(&format!("[34]   via birthplace: {}", matched_birth));
    log(&format!("[34] Unmatched (no country): {}", unmatched));

    // Top 15 countries
    let mut top = conn.prepare(
        "SELECT iso_country_name, iso_a3_code, COUNT(*) as cnt FROM individuals_countries GROUP BY iso_country_name ORDER BY cnt DESC LIMIT 15",
    )?;
    let rows: Vec<(String, String, i64)> = top
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[34] Top 15 countries:");
    for (name, iso, cnt) in &rows {
        log(&format!("[34]   {} ({}) -> {}", name, iso, cnt));
    }

    log("=== Step 34 complete ===");
    Ok(())
}
