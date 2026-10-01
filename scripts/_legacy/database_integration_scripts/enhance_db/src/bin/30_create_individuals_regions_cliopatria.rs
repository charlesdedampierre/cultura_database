/// Create individuals_regions_cliopatria table:
/// For each individual, store their wikidata_id, name, and a Wikipedia URL
/// sourced from (in priority order):
/// 1. nationalities en_wikipedia_url
/// 2. death city en_wikipedia_url_original_country_name
/// 3. birth city en_wikipedia_url_original_country_name
/// With an "origin" column indicating which source was used.
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
    log("=== Step 30: Create individuals_regions_cliopatria table ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // Build nationality name -> en_wikipedia_url lookup
    log("[30] Building nationality URL lookup...");
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
        "[30] Nationality URL lookup: {} entries",
        nat_url_lookup.len()
    ));

    // Build city name -> en_wikipedia_url_original_country_name lookup
    log("[30] Building city URL lookup...");
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
        "[30] City URL lookup: {} entries",
        city_url_lookup.len()
    ));

    // Drop and create the target table
    log("[30] Creating individuals_regions_cliopatria table...");
    conn.execute_batch("DROP TABLE IF EXISTS individuals_regions_cliopatria;")?;
    conn.execute_batch(
        "CREATE TABLE individuals_regions_cliopatria (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            en_wikipedia_url TEXT,
            origin TEXT NOT NULL
        );",
    )?;

    // Count total individuals
    let total: i64 = conn.query_row("SELECT COUNT(*) FROM individuals", [], |r| r.get(0))?;
    log(&format!("[30] Total individuals: {}", total));

    let pb = ProgressBar::new(total as u64);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{msg} [{bar:40}] {pos}/{len} ({eta})")
            .unwrap(),
    );
    pb.set_message("Creating cliopatria");

    let mut offset: i64 = 0;
    let mut from_nationality = 0u64;
    let mut from_deathcity = 0u64;
    let mut from_birthcity = 0u64;
    let mut no_url = 0u64;
    let mut total_inserted = 0u64;

    loop {
        // Read batch of individuals
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
                "INSERT OR IGNORE INTO individuals_regions_cliopatria (wikidata_id, name_en, en_wikipedia_url, origin)
                 VALUES (?1, ?2, ?3, ?4)",
            )?;

            for (wikidata_id, name_en, nationalities_en, deathcity_en, birthcity_en) in &batch {
                let mut found = false;

                // Priority 1: nationality en_wikipedia_url
                if let Some(nats) = nationalities_en {
                    for nat_name in nats.split("; ") {
                        let nat_name = nat_name.trim();
                        if let Some(url) = nat_url_lookup.get(nat_name) {
                            insert.execute(params![
                                wikidata_id,
                                name_en,
                                url,
                                "nationality"
                            ])?;
                            from_nationality += 1;
                            total_inserted += 1;
                            found = true;
                            break;
                        }
                    }
                }

                if found {
                    continue;
                }

                // Priority 2: death city en_wikipedia_url_original_country_name
                if let Some(city) = deathcity_en {
                    let city = city.trim();
                    if let Some(url) = city_url_lookup.get(city) {
                        insert.execute(params![
                            wikidata_id,
                            name_en,
                            url,
                            "deathcity"
                        ])?;
                        from_deathcity += 1;
                        total_inserted += 1;
                        found = true;
                    }
                }

                if found {
                    continue;
                }

                // Priority 3: birth city en_wikipedia_url_original_country_name
                if let Some(city) = birthcity_en {
                    let city = city.trim();
                    if let Some(url) = city_url_lookup.get(city) {
                        insert.execute(params![
                            wikidata_id,
                            name_en,
                            url,
                            "birthcity"
                        ])?;
                        from_birthcity += 1;
                        total_inserted += 1;
                        found = true;
                    }
                }

                if !found {
                    no_url += 1;
                }
            }
        }
        conn.execute_batch("COMMIT;")?;

        pb.inc(batch.len() as u64);
        offset += batch.len() as i64;

        // Log progress every 500k
        if offset % 500_000 < BATCH_SIZE as i64 {
            log(&format!(
                "[30] Progress: {}/{} processed, {} inserted (nat:{}, death:{}, birth:{}), {} no URL",
                offset, total, total_inserted, from_nationality, from_deathcity, from_birthcity, no_url
            ));
        }
    }
    pb.finish();

    // Create indexes
    log("[30] Creating indexes...");
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_cliopatria_url ON individuals_regions_cliopatria(en_wikipedia_url);",
    )?;
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_cliopatria_origin ON individuals_regions_cliopatria(origin);",
    )?;

    // Final stats
    let final_count: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals_regions_cliopatria",
        [],
        |r| r.get(0),
    )?;

    log("[30] === Final Statistics ===");
    log(&format!("[30] Total individuals: {}", total));
    log(&format!("[30] Total inserted: {}", total_inserted));
    log(&format!("[30]   via nationality: {}", from_nationality));
    log(&format!("[30]   via deathcity: {}", from_deathcity));
    log(&format!("[30]   via birthcity: {}", from_birthcity));
    log(&format!("[30] No URL found: {}", no_url));
    log(&format!(
        "[30] Rows in individuals_regions_cliopatria: {}",
        final_count
    ));

    // Show origin breakdown
    let mut stmt = conn.prepare(
        "SELECT origin, COUNT(*) as cnt FROM individuals_regions_cliopatria GROUP BY origin ORDER BY cnt DESC",
    )?;
    let rows: Vec<(String, i64)> = stmt
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[30] Origin breakdown:");
    for (origin, cnt) in &rows {
        log(&format!("[30]   {} -> {}", origin, cnt));
    }

    log("=== Step 30 complete ===");
    Ok(())
}
