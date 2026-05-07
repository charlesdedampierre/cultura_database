/// Fix cities table:
/// - Remove old iso_a3 column (was based on country_name matching)
/// - Add modern_country_name and iso_a3_code from reverse geocoding results
use anyhow::Result;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection};
use std::collections::HashMap;
use std::fs;
use std::io::Write;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const GEOCODED_PATH: &str = "data/all_humans/city_modern_countries.json";
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
    log("=== Step 21: Fix cities - add modern_country from reverse geocoding ===");

    // Load geocoded data - parse streaming to avoid huge memory spike
    log("[21] Loading reverse geocoded city countries...");
    let geocoded_raw = fs::read_to_string(GEOCODED_PATH)?;
    let geocoded: HashMap<String, serde_json::Value> = serde_json::from_str(&geocoded_raw)?;
    log(&format!("[21] Loaded {} geocoded city entries", geocoded.len()));

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // Read existing cities
    log("[21] Reading existing cities...");
    let total: i64 = conn.query_row("SELECT COUNT(*) FROM cities", [], |r| r.get(0))?;
    log(&format!("[21] Total cities: {}", total));

    // Recreate table with new schema (remove iso_a3, add modern_country_name + iso_a3_code)
    log("[21] Recreating cities table with new schema...");
    conn.execute_batch("DROP TABLE IF EXISTS cities_new;")?;
    conn.execute_batch(
        "CREATE TABLE cities_new (
            id TEXT PRIMARY KEY,
            name_en TEXT,
            lat REAL,
            lon REAL,
            country_name TEXT,
            modern_country_name TEXT,
            iso_a3_code TEXT
        );"
    )?;

    // Read all existing data and insert with new columns
    let mut read_stmt = conn.prepare(
        "SELECT id, name_en, lat, lon, country_name FROM cities ORDER BY rowid"
    )?;

    let rows: Vec<(String, Option<String>, Option<f64>, Option<f64>, Option<String>)> = read_stmt
        .query_map([], |r| {
            Ok((
                r.get(0)?,
                r.get(1)?,
                r.get(2)?,
                r.get(3)?,
                r.get(4)?,
            ))
        })?
        .filter_map(|r| r.ok())
        .collect();

    log(&format!("[21] Read {} cities, inserting with modern_country...", rows.len()));

    let pb = ProgressBar::new(rows.len() as u64);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{msg} [{bar:40}] {pos}/{len} ({eta})")
            .unwrap(),
    );
    pb.set_message("Inserting cities");

    let mut mapped = 0u64;
    let mut unmapped = 0u64;

    conn.execute_batch("BEGIN TRANSACTION;")?;
    {
        let mut insert = conn.prepare(
            "INSERT INTO cities_new (id, name_en, lat, lon, country_name, modern_country_name, iso_a3_code)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)"
        )?;

        for (id, name_en, lat, lon, country_name) in &rows {
            let (modern_name, iso_code) = if let Some(geo) = geocoded.get(id) {
                let cn = geo.get("country_name").and_then(|v| v.as_str()).map(String::from);
                let iso = geo.get("iso_a3_code").and_then(|v| v.as_str()).map(String::from);
                if cn.is_some() {
                    mapped += 1;
                } else {
                    unmapped += 1;
                }
                (cn, iso)
            } else {
                unmapped += 1;
                (None, None)
            };

            insert.execute(params![id, name_en, lat, lon, country_name, modern_name, iso_code])?;
            pb.inc(1);
        }
    }
    conn.execute_batch("COMMIT;")?;
    pb.finish();

    // Swap tables
    log("[21] Swapping tables...");
    conn.execute_batch("DROP TABLE cities;")?;
    conn.execute_batch("ALTER TABLE cities_new RENAME TO cities;")?;

    // Create indexes
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_cities_name ON cities(name_en);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_cities_iso ON cities(iso_a3_code);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_cities_modern_country ON cities(modern_country_name);")?;

    log(&format!("[21] Mapped: {}, Unmapped: {}", mapped, unmapped));

    // Show samples
    let mut sample = conn.prepare(
        "SELECT id, name_en, country_name, modern_country_name, iso_a3_code FROM cities LIMIT 10"
    )?;
    let sample_rows: Vec<(String, Option<String>, Option<String>, Option<String>, Option<String>)> = sample
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?)))?
        .filter_map(|r| r.ok())
        .collect();
    for (id, name, cn, mcn, iso) in &sample_rows {
        log(&format!(
            "[21]   {} ({}) country={} -> modern={} ({})",
            id,
            name.as_deref().unwrap_or("?"),
            cn.as_deref().unwrap_or("?"),
            mcn.as_deref().unwrap_or("?"),
            iso.as_deref().unwrap_or("?")
        ));
    }

    // Show how many historical countries are now resolved
    let resolved: i64 = conn.query_row(
        "SELECT COUNT(*) FROM cities WHERE modern_country_name IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    log(&format!("[21] Cities with modern_country: {} / {}", resolved, total));

    log("=== Step 21 complete ===");
    Ok(())
}
