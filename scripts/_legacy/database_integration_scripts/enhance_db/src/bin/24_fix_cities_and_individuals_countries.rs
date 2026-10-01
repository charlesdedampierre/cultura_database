/// Step 24: Fix cities and rebuild individuals_countries
///
/// 1. cities: rename en_wikipedia_url_country -> en_wikipedia_url_original_country_name
/// 2. cities: where lat=0.0 AND lon=0.0, set lat/lon/iso_country_name/iso_a3_code to NULL
/// 3. Rebuild individuals_countries with name_en column added
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
    log("=== Step 24: Fix cities and rebuild individuals_countries ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // ==========================================
    // 1. Fix cities: rename column + nullify 0,0 coords
    // ==========================================
    log("[24] Fixing cities table...");

    let total_cities: i64 = conn.query_row("SELECT COUNT(*) FROM cities", [], |r| r.get(0))?;
    let zero_zero: i64 = conn.query_row(
        "SELECT COUNT(*) FROM cities WHERE lat = 0.0 AND lon = 0.0",
        [],
        |r| r.get(0),
    )?;
    log(&format!(
        "[24] Total cities: {}, with 0,0 coords: {}",
        total_cities, zero_zero
    ));

    // Recreate table with renamed column and fix 0,0 in one pass
    conn.execute_batch(
        "DROP TABLE IF EXISTS cities_new;
        CREATE TABLE cities_new (
            id TEXT PRIMARY KEY,
            name_en TEXT,
            lat REAL,
            lon REAL,
            original_country_name TEXT,
            original_country_name_id TEXT,
            en_wikipedia_url_original_country_name TEXT,
            iso_country_name TEXT,
            iso_a3_code TEXT
        );

        INSERT INTO cities_new (id, name_en, lat, lon, original_country_name, original_country_name_id, en_wikipedia_url_original_country_name, iso_country_name, iso_a3_code)
        SELECT
            id,
            name_en,
            CASE WHEN lat = 0.0 AND lon = 0.0 THEN NULL ELSE lat END,
            CASE WHEN lat = 0.0 AND lon = 0.0 THEN NULL ELSE lon END,
            original_country_name,
            original_country_name_id,
            en_wikipedia_url_country,
            CASE WHEN lat = 0.0 AND lon = 0.0 THEN NULL ELSE iso_country_name END,
            CASE WHEN lat = 0.0 AND lon = 0.0 THEN NULL ELSE iso_a3_code END
        FROM cities;

        DROP TABLE cities;
        ALTER TABLE cities_new RENAME TO cities;

        CREATE INDEX IF NOT EXISTS idx_cities_name ON cities(name_en);
        CREATE INDEX IF NOT EXISTS idx_cities_iso_country ON cities(iso_country_name);
        CREATE INDEX IF NOT EXISTS idx_cities_iso ON cities(iso_a3_code);
        CREATE INDEX IF NOT EXISTS idx_cities_orig_country_id ON cities(original_country_name_id);",
    )?;

    // Verify
    let null_coords: i64 = conn.query_row(
        "SELECT COUNT(*) FROM cities WHERE lat IS NULL AND lon IS NULL",
        [],
        |r| r.get(0),
    )?;
    let ghana_count: i64 = conn.query_row(
        "SELECT COUNT(*) FROM cities WHERE iso_country_name = 'Ghana'",
        [],
        |r| r.get(0),
    )?;
    log(&format!(
        "[24] Cities with NULL coords now: {} (was {} at 0,0)",
        null_coords, zero_zero
    ));
    log(&format!(
        "[24] Ghana cities remaining (legitimate): {}",
        ghana_count
    ));

    // Show sample
    let mut sample = conn.prepare(
        "SELECT id, name_en, lat, lon, original_country_name, iso_country_name, iso_a3_code
         FROM cities WHERE original_country_name = 'Spain' AND lat IS NULL LIMIT 3",
    )?;
    let rows: Vec<(String, Option<String>, Option<f64>, Option<f64>, Option<String>, Option<String>, Option<String>)> = sample
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?, r.get(5)?, r.get(6)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[24] Sample fixed 0,0 cities:");
    for (id, name, lat, lon, orig, iso, code) in &rows {
        log(&format!(
            "[24]   {} ({}) lat={:?} lon={:?} orig={} iso={:?} code={:?}",
            id,
            name.as_deref().unwrap_or("?"),
            lat,
            lon,
            orig.as_deref().unwrap_or("?"),
            iso,
            code
        ));
    }

    // ==========================================
    // 2. Rebuild individuals_countries with name_en
    // ==========================================
    log("[24] Rebuilding individuals_countries with name_en...");

    // Build nationality name -> (iso_country_name, iso_a3_code) lookup
    log("[24] Building nationality lookup...");
    let mut nat_lookup: HashMap<String, (String, String)> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT name_en, iso_country_name, iso_a3_code FROM nationalities WHERE iso_country_name IS NOT NULL AND iso_a3_code IS NOT NULL",
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
    log(&format!("[24] Nationality lookup: {} entries", nat_lookup.len()));

    // Build city name -> (iso_country_name, iso_a3_code) lookup
    log("[24] Building city lookup...");
    let mut city_lookup: HashMap<String, (String, String)> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT name_en, iso_country_name, iso_a3_code FROM cities WHERE iso_country_name IS NOT NULL AND iso_a3_code IS NOT NULL",
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
    log(&format!("[24] City lookup: {} entries", city_lookup.len()));

    // Drop and recreate with name_en column
    conn.execute_batch("DROP TABLE IF EXISTS individuals_countries;")?;
    conn.execute_batch(
        "CREATE TABLE individuals_countries (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            iso_country_name TEXT NOT NULL,
            iso_a3_code TEXT NOT NULL,
            origins TEXT NOT NULL
        );",
    )?;

    let total: i64 =
        conn.query_row("SELECT COUNT(*) FROM individuals", [], |r| r.get(0))?;
    log(&format!("[24] Total individuals: {}", total));

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
                let mut found = false;

                // Priority 1: nationality
                if let Some(nats) = nationalities_en {
                    for nat_name in nats.split("; ") {
                        let nat_name = nat_name.trim();
                        if let Some((country, iso)) = nat_lookup.get(nat_name) {
                            insert.execute(params![
                                wikidata_id,
                                name_en,
                                country,
                                iso,
                                "nationality"
                            ])?;
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
                        insert.execute(params![
                            wikidata_id,
                            name_en,
                            country,
                            iso,
                            "deathplace"
                        ])?;
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
                        insert.execute(params![
                            wikidata_id,
                            name_en,
                            country,
                            iso,
                            "birthplace"
                        ])?;
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

        if offset % 500_000 < BATCH_SIZE as i64 {
            log(&format!(
                "[24] Progress: {}/{} processed, {} inserted (nat:{}, death:{}, birth:{}), {} unmatched",
                offset, total, total_inserted, matched_nationality, matched_death, matched_birth, unmatched
            ));
        }
    }
    pb.finish();

    // Create indexes
    log("[24] Creating indexes...");
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_indcountries_iso_country ON individuals_countries(iso_country_name);
         CREATE INDEX IF NOT EXISTS idx_indcountries_iso ON individuals_countries(iso_a3_code);
         CREATE INDEX IF NOT EXISTS idx_indcountries_origins ON individuals_countries(origins);",
    )?;

    let final_count: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals_countries",
        [],
        |r| r.get(0),
    )?;

    log("[24] === Final Statistics ===");
    log(&format!("[24] Total individuals: {}", total));
    log(&format!("[24] Total matched: {}", total_inserted));
    log(&format!("[24]   via nationality: {}", matched_nationality));
    log(&format!("[24]   via deathplace: {}", matched_death));
    log(&format!("[24]   via birthplace: {}", matched_birth));
    log(&format!("[24] Unmatched: {}", unmatched));
    log(&format!(
        "[24] Rows in individuals_countries: {}",
        final_count
    ));
    log(&format!(
        "[24] Previous run had 6,374,643 matched. New run: {} (diff: {})",
        total_inserted,
        total_inserted as i64 - 6_374_643
    ));

    // Top countries
    let mut top = conn.prepare(
        "SELECT iso_country_name, iso_a3_code, COUNT(*) as cnt FROM individuals_countries GROUP BY iso_country_name ORDER BY cnt DESC LIMIT 15",
    )?;
    let rows: Vec<(String, String, i64)> = top
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[24] Top 15 countries:");
    for (name, iso, cnt) in &rows {
        log(&format!("[24]   {} ({}) -> {}", name, iso, cnt));
    }

    // Sample with name
    let mut name_sample = conn.prepare(
        "SELECT wikidata_id, name_en, iso_country_name, iso_a3_code, origins FROM individuals_countries LIMIT 5",
    )?;
    let name_rows: Vec<(String, Option<String>, String, String, String)> = name_sample
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[24] Sample with name_en:");
    for (wid, name, cn, iso, orig) in &name_rows {
        log(&format!(
            "[24]   {} ({}) -> {} ({}) [{}]",
            wid,
            name.as_deref().unwrap_or("?"),
            cn,
            iso,
            orig
        ));
    }

    // Verify no Ghana from 0,0
    let ghana_ind: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals_countries WHERE iso_country_name = 'Ghana'",
        [],
        |r| r.get(0),
    )?;
    log(&format!(
        "[24] Ghana in individuals_countries: {} (should be only legitimate ones)",
        ghana_ind
    ));

    // Final schemas
    log("[24] === Final Schemas ===");
    for table in &["cities", "individuals_countries"] {
        let mut stmt = conn.prepare(&format!("PRAGMA table_info({})", table))?;
        let cols: Vec<String> = stmt
            .query_map([], |r| {
                let name: String = r.get(1)?;
                let typ: String = r.get(2)?;
                Ok(format!("{} {}", name, typ))
            })?
            .filter_map(|r| r.ok())
            .collect();
        log(&format!("[24] {}: {:?}", table, cols));
    }

    log("=== Step 24 complete ===");
    Ok(())
}
