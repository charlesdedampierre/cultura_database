/// Step 23: Rename columns and enrich cities
///
/// 1. nationalities: rename country_name -> iso_country_name
/// 2. cities: rename modern_country_name -> iso_country_name
///           rename country_name -> original_country_name
///           add original_country_name_id (wikidata ID)
///           add en_wikipedia_url_country (English Wikipedia URL for the original country)
/// 3. individuals_countries: rename country_name -> iso_country_name
use anyhow::Result;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection};
use serde_json::Value;
use std::collections::HashMap;
use std::fs;
use std::io::Write;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const PLACE_LOCATIONS_PATH: &str = "data/all_humans/place_locations.json";
const COUNTRY_WIKI_PATH: &str = "data/all_humans/country_wikipedia_urls.json";
const TASK_LOG: &str = "task.log";

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
    log("=== Step 23: Rename columns and enrich cities ===");

    // Load place_locations for city_id -> country_id mapping
    log("[23] Loading place_locations...");
    let pl_raw = fs::read_to_string(PLACE_LOCATIONS_PATH)?;
    let place_locations: HashMap<String, Value> = serde_json::from_str(&pl_raw)?;
    log(&format!("[23] Loaded {} place locations", place_locations.len()));

    // Build city_id -> country_id lookup
    let mut city_country_id: HashMap<String, String> = HashMap::new();
    for (city_id, val) in &place_locations {
        if let Some(cid) = val.get("country_id").and_then(|v| v.as_str()) {
            city_country_id.insert(city_id.clone(), cid.to_string());
        }
    }
    log(&format!("[23] City -> country_id mappings: {}", city_country_id.len()));

    // Load country wikipedia URLs
    log("[23] Loading country Wikipedia URLs...");
    let cw_raw = fs::read_to_string(COUNTRY_WIKI_PATH)?;
    let country_wiki: HashMap<String, Value> = serde_json::from_str(&cw_raw)?;
    log(&format!("[23] Loaded {} country wiki entries", country_wiki.len()));

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // ==========================================
    // 1. Fix nationalities: rename country_name -> iso_country_name
    // ==========================================
    log("[23] Fixing nationalities table...");
    {
        let count: i64 = conn.query_row("SELECT COUNT(*) FROM nationalities", [], |r| r.get(0))?;

        conn.execute_batch(
            "CREATE TABLE nationalities_new (
                wikidata_id TEXT PRIMARY KEY,
                name_en TEXT,
                count INTEGER DEFAULT 0,
                description_en TEXT,
                instance_of TEXT,
                en_wikipedia_url TEXT,
                lat REAL,
                lon REAL,
                iso_country_name TEXT,
                iso_a3_code TEXT
            );

            INSERT INTO nationalities_new
            SELECT wikidata_id, name_en, count, description_en, instance_of, en_wikipedia_url, lat, lon, country_name, iso_a3_code
            FROM nationalities;

            DROP TABLE nationalities;
            ALTER TABLE nationalities_new RENAME TO nationalities;

            CREATE INDEX IF NOT EXISTS idx_nationalities_name ON nationalities(name_en);
            CREATE INDEX IF NOT EXISTS idx_nationalities_iso_country ON nationalities(iso_country_name);
            CREATE INDEX IF NOT EXISTS idx_nationalities_iso ON nationalities(iso_a3_code);"
        )?;

        log(&format!("[23] Nationalities: renamed country_name -> iso_country_name ({} rows)", count));
    }

    // ==========================================
    // 2. Fix cities: rename + add columns
    // ==========================================
    log("[23] Fixing cities table...");
    {
        // Read all existing cities
        let mut cities: Vec<(String, Option<String>, Option<f64>, Option<f64>, Option<String>, Option<String>, Option<String>)> = Vec::new();
        {
            let mut stmt = conn.prepare(
                "SELECT id, name_en, lat, lon, country_name, modern_country_name, iso_a3_code FROM cities"
            )?;
            let rows = stmt.query_map([], |r| {
                Ok((
                    r.get(0)?,
                    r.get(1)?,
                    r.get(2)?,
                    r.get(3)?,
                    r.get(4)?,
                    r.get(5)?,
                    r.get(6)?,
                ))
            })?;
            for r in rows {
                cities.push(r?);
            }
        }
        log(&format!("[23] Read {} cities", cities.len()));

        conn.execute_batch(
            "DROP TABLE IF EXISTS cities_new;
            CREATE TABLE cities_new (
                id TEXT PRIMARY KEY,
                name_en TEXT,
                lat REAL,
                lon REAL,
                original_country_name TEXT,
                original_country_name_id TEXT,
                en_wikipedia_url_country TEXT,
                iso_country_name TEXT,
                iso_a3_code TEXT
            );"
        )?;

        let pb = ProgressBar::new(cities.len() as u64);
        pb.set_style(
            ProgressStyle::default_bar()
                .template("{msg} [{bar:40}] {pos}/{len} ({eta})")
                .unwrap(),
        );
        pb.set_message("Inserting cities");

        let mut with_id = 0u64;
        let mut with_wiki = 0u64;

        conn.execute_batch("BEGIN TRANSACTION;")?;
        {
            let mut insert = conn.prepare(
                "INSERT INTO cities_new (id, name_en, lat, lon, original_country_name, original_country_name_id, en_wikipedia_url_country, iso_country_name, iso_a3_code)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)"
            )?;

            for (id, name_en, lat, lon, country_name, modern_country_name, iso_a3_code) in &cities {
                // Get original_country_name_id from place_locations
                let country_id = city_country_id.get(id);

                // Get en_wikipedia_url from country_wiki
                let wiki_url = country_id.and_then(|cid| {
                    country_wiki.get(cid).and_then(|v| {
                        v.get("en_wikipedia_url").and_then(|u| u.as_str()).map(String::from)
                    })
                });

                if country_id.is_some() {
                    with_id += 1;
                }
                if wiki_url.is_some() {
                    with_wiki += 1;
                }

                insert.execute(params![
                    id,
                    name_en,
                    lat,
                    lon,
                    country_name,       // country_name -> original_country_name
                    country_id,         // new: original_country_name_id
                    wiki_url,           // new: en_wikipedia_url_country
                    modern_country_name, // modern_country_name -> iso_country_name
                    iso_a3_code,
                ])?;
                pb.inc(1);
            }
        }
        conn.execute_batch("COMMIT;")?;
        pb.finish();

        conn.execute_batch(
            "DROP TABLE cities;
            ALTER TABLE cities_new RENAME TO cities;

            CREATE INDEX IF NOT EXISTS idx_cities_name ON cities(name_en);
            CREATE INDEX IF NOT EXISTS idx_cities_iso_country ON cities(iso_country_name);
            CREATE INDEX IF NOT EXISTS idx_cities_iso ON cities(iso_a3_code);
            CREATE INDEX IF NOT EXISTS idx_cities_orig_country_id ON cities(original_country_name_id);"
        )?;

        log(&format!("[23] Cities: with original_country_name_id: {}, with Wikipedia URL: {}", with_id, with_wiki));

        // Show samples
        let mut sample = conn.prepare(
            "SELECT id, name_en, original_country_name, original_country_name_id, en_wikipedia_url_country, iso_country_name, iso_a3_code
             FROM cities LIMIT 5"
        )?;
        let rows: Vec<(String, Option<String>, Option<String>, Option<String>, Option<String>, Option<String>, Option<String>)> = sample
            .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?, r.get(5)?, r.get(6)?)))?
            .filter_map(|r| r.ok())
            .collect();
        for (id, name, orig_cn, orig_id, wiki, iso_cn, iso) in &rows {
            log(&format!(
                "[23]   {} ({}) orig={} ({}) wiki={} iso={} ({})",
                id,
                name.as_deref().unwrap_or("?"),
                orig_cn.as_deref().unwrap_or("?"),
                orig_id.as_deref().unwrap_or("?"),
                wiki.as_deref().unwrap_or("?"),
                iso_cn.as_deref().unwrap_or("?"),
                iso.as_deref().unwrap_or("?")
            ));
        }

        // Show a historical country example
        let mut hist = conn.prepare(
            "SELECT id, name_en, original_country_name, original_country_name_id, en_wikipedia_url_country, iso_country_name, iso_a3_code
             FROM cities WHERE original_country_name != iso_country_name LIMIT 5"
        )?;
        let hist_rows: Vec<(String, Option<String>, Option<String>, Option<String>, Option<String>, Option<String>, Option<String>)> = hist
            .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?, r.get(5)?, r.get(6)?)))?
            .filter_map(|r| r.ok())
            .collect();
        if !hist_rows.is_empty() {
            log("[23] Cities where original != modern:");
            for (id, name, orig_cn, orig_id, wiki, iso_cn, iso) in &hist_rows {
                log(&format!(
                    "[23]   {} ({}) orig={} ({}) wiki={} -> iso={} ({})",
                    id,
                    name.as_deref().unwrap_or("?"),
                    orig_cn.as_deref().unwrap_or("?"),
                    orig_id.as_deref().unwrap_or("?"),
                    wiki.as_deref().unwrap_or("None"),
                    iso_cn.as_deref().unwrap_or("?"),
                    iso.as_deref().unwrap_or("?")
                ));
            }
        }
    }

    // ==========================================
    // 3. Fix individuals_countries: rename country_name -> iso_country_name
    // ==========================================
    log("[23] Fixing individuals_countries table...");
    {
        let count: i64 = conn.query_row("SELECT COUNT(*) FROM individuals_countries", [], |r| r.get(0))?;

        conn.execute_batch(
            "CREATE TABLE individuals_countries_new (
                wikidata_id TEXT PRIMARY KEY,
                iso_country_name TEXT NOT NULL,
                iso_a3_code TEXT NOT NULL,
                origins TEXT NOT NULL
            );

            INSERT INTO individuals_countries_new
            SELECT wikidata_id, country_name, iso_a3_code, origins
            FROM individuals_countries;

            DROP TABLE individuals_countries;
            ALTER TABLE individuals_countries_new RENAME TO individuals_countries;

            CREATE INDEX IF NOT EXISTS idx_indcountries_iso_country ON individuals_countries(iso_country_name);
            CREATE INDEX IF NOT EXISTS idx_indcountries_iso ON individuals_countries(iso_a3_code);
            CREATE INDEX IF NOT EXISTS idx_indcountries_origins ON individuals_countries(origins);"
        )?;

        log(&format!("[23] individuals_countries: renamed country_name -> iso_country_name ({} rows)", count));
    }

    // Final schema check
    log("[23] === Final Schemas ===");
    for table in &["nationalities", "cities", "individuals_countries"] {
        let mut stmt = conn.prepare(&format!("PRAGMA table_info({})", table))?;
        let cols: Vec<(i32, String, String)> = stmt
            .query_map([], |r| Ok((r.get(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?)))?
            .filter_map(|r| r.ok())
            .collect();
        log(&format!("[23] {}: {:?}", table, cols.iter().map(|(_, n, t)| format!("{} {}", n, t)).collect::<Vec<_>>()));
    }

    log("=== Step 23 complete ===");
    Ok(())
}
