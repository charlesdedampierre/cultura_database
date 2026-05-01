/// Create individuals_regions_cliopatria table.
/// Associates each individual with a Wikipedia URL based on:
/// 1. nationality en_wikipedia_url (first priority)
/// 2. deathcity en_wikipedia_url_original_country_name (second priority)
/// 3. birthcity en_wikipedia_url_original_country_name (third priority)
/// Adds an "origin" column indicating the source.
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
    let _ = fs::remove_file(TASK_LOG);
    log("=== Step 35: Create individuals_regions_cliopatria ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // ========================================================
    // PHASE 1: Build lookups
    // ========================================================

    // Nationality name -> en_wikipedia_url
    log("[35] Building nationality URL lookup...");
    let mut nat_url_lookup: HashMap<String, String> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT name_en, en_wikipedia_url FROM nationalities WHERE en_wikipedia_url IS NOT NULL",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
        })?;
        for r in rows {
            let (name, url) = r?;
            nat_url_lookup.insert(name, url);
        }
    }
    log(&format!(
        "[35] Nationality URL lookup: {} entries",
        nat_url_lookup.len()
    ));

    // City name -> en_wikipedia_url_original_country_name
    log("[35] Building city URL lookup...");
    let mut city_url_lookup: HashMap<String, String> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT name_en, en_wikipedia_url_original_country_name FROM cities WHERE en_wikipedia_url_original_country_name IS NOT NULL",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
        })?;
        for r in rows {
            let (name, url) = r?;
            city_url_lookup.entry(name).or_insert(url);
        }
    }
    log(&format!(
        "[35] City URL lookup: {} entries",
        city_url_lookup.len()
    ));

    // ========================================================
    // PHASE 2: Drop and recreate table
    // ========================================================
    log("[35] Creating fresh individuals_regions_cliopatria table...");
    conn.execute_batch("DROP TABLE IF EXISTS individuals_regions_cliopatria;")?;
    conn.execute_batch(
        "CREATE TABLE individuals_regions_cliopatria (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            url TEXT,
            origin TEXT
        );",
    )?;
    log("[35] Created fresh individuals_regions_cliopatria table");

    // ========================================================
    // PHASE 3: Populate
    // ========================================================
    let total: i64 = conn.query_row("SELECT COUNT(*) FROM individuals", [], |r| r.get(0))?;
    log(&format!("[35] Total individuals to process: {}", total));

    let pb = ProgressBar::new(total as u64);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{msg} [{bar:40}] {pos}/{len} ({eta})")
            .unwrap(),
    );
    pb.set_message("Creating individuals_regions_cliopatria");

    let mut offset: i64 = 0;
    let mut matched_nationality = 0u64;
    let mut matched_death = 0u64;
    let mut matched_birth = 0u64;
    let mut unmatched = 0u64;
    let mut total_inserted = 0u64;

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
                "INSERT OR IGNORE INTO individuals_regions_cliopatria (wikidata_id, name_en, url, origin)
                 VALUES (?1, ?2, ?3, ?4)",
            )?;

            for (wikidata_id, name_en, nationalities_en, deathcity_en, birthcity_en) in &batch {
                let mut found: Option<(String, &str)> = None;

                // Priority 1: nationality URL
                if let Some(nats) = nationalities_en {
                    for nat_name in nats.split("; ") {
                        let nat_name = nat_name.trim();
                        if let Some(url) = nat_url_lookup.get(nat_name) {
                            found = Some((url.clone(), "nationality"));
                            break;
                        }
                    }
                }

                // Priority 2: deathcity URL
                if found.is_none() {
                    if let Some(city) = deathcity_en {
                        let city = city.trim();
                        if let Some(url) = city_url_lookup.get(city) {
                            found = Some((url.clone(), "deathplace"));
                        }
                    }
                }

                // Priority 3: birthcity URL
                if found.is_none() {
                    if let Some(city) = birthcity_en {
                        let city = city.trim();
                        if let Some(url) = city_url_lookup.get(city) {
                            found = Some((url.clone(), "birthplace"));
                        }
                    }
                }

                if let Some((url, origin)) = found {
                    insert.execute(params![wikidata_id, name_en, url, origin])?;

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
                "[35] Progress: {}/{} processed, {} inserted (nat:{}, death:{}, birth:{}), {} unmatched",
                offset, total, total_inserted, matched_nationality, matched_death, matched_birth, unmatched
            ));
        }
    }
    pb.finish();

    // ========================================================
    // PHASE 4: Create indexes
    // ========================================================
    log("[35] Creating indexes...");
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_irc_origin ON individuals_regions_cliopatria(origin);",
    )?;
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_irc_url ON individuals_regions_cliopatria(url);",
    )?;

    // ========================================================
    // PHASE 5: Final stats
    // ========================================================
    let final_count: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals_regions_cliopatria",
        [],
        |r| r.get(0),
    )?;

    log("[35] === Final Statistics ===");
    log(&format!("[35] Total individuals: {}", total));
    log(&format!(
        "[35] Total in individuals_regions_cliopatria: {}",
        final_count
    ));
    log(&format!("[35]   via nationality: {}", matched_nationality));
    log(&format!("[35]   via deathplace: {}", matched_death));
    log(&format!("[35]   via birthplace: {}", matched_birth));
    log(&format!("[35] Unmatched (no URL): {}", unmatched));

    // Top 15 URLs
    let mut top = conn.prepare(
        "SELECT url, COUNT(*) as cnt FROM individuals_regions_cliopatria GROUP BY url ORDER BY cnt DESC LIMIT 15",
    )?;
    let rows: Vec<(String, i64)> = top
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[35] Top 15 URLs:");
    for (url, cnt) in &rows {
        log(&format!("[35]   {} -> {}", url, cnt));
    }

    // Origin breakdown
    let mut origins = conn.prepare(
        "SELECT origin, COUNT(*) as cnt FROM individuals_regions_cliopatria GROUP BY origin ORDER BY cnt DESC",
    )?;
    let rows: Vec<(String, i64)> = origins
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[35] Origin breakdown:");
    for (origin, cnt) in &rows {
        log(&format!("[35]   {} -> {}", origin, cnt));
    }

    log("=== Step 35 complete ===");
    Ok(())
}
