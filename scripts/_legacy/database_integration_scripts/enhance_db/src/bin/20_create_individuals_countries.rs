/// Create individuals_countries table:
/// Associate each individual with a modern country based on:
/// 1. nationality (first priority)
/// 2. deathplace (second priority)
/// 3. birthplace (third priority)
/// Includes an "origins" column indicating the source.
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
    log("=== Step 20: Create individuals_countries table ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // Build nationality name -> (country_name, iso_a3_code) lookup
    log("[20] Building nationality lookup...");
    let mut nat_lookup: HashMap<String, (String, String)> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT name_en, country_name, iso_a3_code FROM nationalities WHERE country_name IS NOT NULL AND iso_a3_code IS NOT NULL"
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
    log(&format!("[20] Nationality lookup: {} entries", nat_lookup.len()));

    // Build city name -> (country_name, iso_a3) lookup
    log("[20] Building city lookup...");
    let mut city_lookup: HashMap<String, (String, String)> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT name_en, country_name, iso_a3 FROM cities WHERE country_name IS NOT NULL AND iso_a3 IS NOT NULL"
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
            // For duplicate city names, first one wins (they usually have same country)
            city_lookup.entry(name).or_insert((country, iso));
        }
    }
    log(&format!("[20] City lookup: {} entries", city_lookup.len()));

    // Drop and create the target table
    log("[20] Creating individuals_countries table...");
    conn.execute_batch("DROP TABLE IF EXISTS individuals_countries;")?;
    conn.execute_batch(
        "CREATE TABLE individuals_countries (
            wikidata_id TEXT PRIMARY KEY,
            country_name TEXT NOT NULL,
            iso_a3_code TEXT NOT NULL,
            origins TEXT NOT NULL
        );"
    )?;

    // Count total individuals
    let total: i64 = conn.query_row("SELECT COUNT(*) FROM individuals", [], |r| r.get(0))?;
    log(&format!("[20] Total individuals: {}", total));

    // Process in batches using LIMIT/OFFSET via rowid ordering
    let pb = ProgressBar::new(total as u64);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{msg} [{bar:40}] {pos}/{len} ({eta})")
            .unwrap(),
    );
    pb.set_message("Processing individuals");

    let mut offset: i64 = 0;
    let mut matched_nationality = 0u64;
    let mut matched_death = 0u64;
    let mut matched_birth = 0u64;
    let mut unmatched = 0u64;
    let mut total_inserted = 0u64;

    loop {
        // Read a batch
        let mut batch: Vec<(String, Option<String>, Option<String>, Option<String>)> = Vec::with_capacity(BATCH_SIZE);
        {
            let mut stmt = conn.prepare_cached(
                "SELECT wikidata_id, nationalities_en, deathcity_en, birthcity_en
                 FROM individuals
                 ORDER BY rowid
                 LIMIT ?1 OFFSET ?2"
            )?;
            let rows = stmt.query_map(params![BATCH_SIZE as i64, offset], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, Option<String>>(1)?,
                    r.get::<_, Option<String>>(2)?,
                    r.get::<_, Option<String>>(3)?,
                ))
            })?;
            for r in rows {
                batch.push(r?);
            }
        }

        if batch.is_empty() {
            break;
        }

        // Process batch and insert
        conn.execute_batch("BEGIN TRANSACTION;")?;
        {
            let mut insert = conn.prepare_cached(
                "INSERT OR IGNORE INTO individuals_countries (wikidata_id, country_name, iso_a3_code, origins)
                 VALUES (?1, ?2, ?3, ?4)"
            )?;

            for (wikidata_id, nationalities_en, deathcity_en, birthcity_en) in &batch {
                let mut found = false;

                // Priority 1: nationality
                if let Some(nats) = nationalities_en {
                    for nat_name in nats.split("; ") {
                        let nat_name = nat_name.trim();
                        if let Some((country, iso)) = nat_lookup.get(nat_name) {
                            insert.execute(params![wikidata_id, country, iso, "nationality"])?;
                            matched_nationality += 1;
                            total_inserted += 1;
                            found = true;
                            break;
                        }
                    }
                }

                if found {
                    continue;
                }

                // Priority 2: deathplace
                if let Some(city) = deathcity_en {
                    let city = city.trim();
                    if let Some((country, iso)) = city_lookup.get(city) {
                        insert.execute(params![wikidata_id, country, iso, "deathplace"])?;
                        matched_death += 1;
                        total_inserted += 1;
                        found = true;
                    }
                }

                if found {
                    continue;
                }

                // Priority 3: birthplace
                if let Some(city) = birthcity_en {
                    let city = city.trim();
                    if let Some((country, iso)) = city_lookup.get(city) {
                        insert.execute(params![wikidata_id, country, iso, "birthplace"])?;
                        matched_birth += 1;
                        total_inserted += 1;
                        found = true;
                    }
                }

                if !found {
                    unmatched += 1;
                }
            }
        }
        conn.execute_batch("COMMIT;")?;

        pb.inc(batch.len() as u64);
        offset += batch.len() as i64;

        // Log progress every 500k
        if offset % 500_000 < BATCH_SIZE as i64 {
            log(&format!(
                "[20] Progress: {}/{} processed, {} inserted (nat:{}, death:{}, birth:{}), {} unmatched",
                offset, total, total_inserted, matched_nationality, matched_death, matched_birth, unmatched
            ));
        }
    }
    pb.finish();

    // Create indexes
    log("[20] Creating indexes...");
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_indcountries_country ON individuals_countries(country_name);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_indcountries_iso ON individuals_countries(iso_a3_code);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_indcountries_origins ON individuals_countries(origins);")?;

    // Final stats
    let final_count: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals_countries",
        [],
        |r| r.get(0),
    )?;

    log(&format!("[20] === Final Statistics ==="));
    log(&format!("[20] Total individuals: {}", total));
    log(&format!("[20] Total matched: {}", total_inserted));
    log(&format!("[20]   via nationality: {}", matched_nationality));
    log(&format!("[20]   via deathplace: {}", matched_death));
    log(&format!("[20]   via birthplace: {}", matched_birth));
    log(&format!("[20] Unmatched: {}", unmatched));
    log(&format!("[20] Rows in individuals_countries: {}", final_count));

    // Show top countries
    let mut top = conn.prepare(
        "SELECT country_name, iso_a3_code, COUNT(*) as cnt FROM individuals_countries GROUP BY country_name ORDER BY cnt DESC LIMIT 15"
    )?;
    let rows: Vec<(String, String, i64)> = top
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[20] Top 15 countries:");
    for (name, iso, cnt) in &rows {
        log(&format!("[20]   {} ({}) -> {}", name, iso, cnt));
    }

    log("=== Step 20 complete ===");
    Ok(())
}
