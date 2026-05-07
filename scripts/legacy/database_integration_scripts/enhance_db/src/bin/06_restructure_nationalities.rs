/// Restructure nationalities table:
/// - Put wikidata_id first
/// - Add en_wikipedia_url column (from extracted sitelinks)
/// - Add lat/lon location columns (from extracted locations)
/// - Add modern_country_name column
use anyhow::Result;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection};
use serde_json::Value;
use std::collections::HashMap;
use std::fs;
use std::io::Write;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const SITELINKS_PATH: &str = "data/all_humans/nationality_sitelinks.json";
const LOCATIONS_PATH: &str = "data/all_humans/nationality_locations.json";
const NAT_COUNTRIES_PATH: &str = "data/all_humans/nationality_countries.json";
const TASK_LOG: &str = "task.log";

fn log(msg: &str) {
    println!("{}", msg);
    let mut f = fs::OpenOptions::new()
        .append(true)
        .open(TASK_LOG)
        .unwrap();
    writeln!(f, "{}", msg).unwrap();
}

fn main() -> Result<()> {
    log("[DB] 06: Restructuring nationalities table...");

    // Load sitelinks
    let sitelinks_json = fs::read_to_string(SITELINKS_PATH)?;
    let sitelinks: HashMap<String, Value> = serde_json::from_str(&sitelinks_json)?;
    log(&format!("[DB] Loaded {} nationality sitelinks", sitelinks.len()));

    // Load locations
    let locations_json = fs::read_to_string(LOCATIONS_PATH)?;
    let locations: HashMap<String, Value> = serde_json::from_str(&locations_json)?;
    log(&format!("[DB] Loaded {} nationality locations", locations.len()));

    // Load nationality -> country mapping
    let nat_countries_json = fs::read_to_string(NAT_COUNTRIES_PATH)?;
    let nat_countries: HashMap<String, Value> = serde_json::from_str(&nat_countries_json)?;
    log(&format!("[DB] Loaded {} nationality->country mappings", nat_countries.len()));

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;")?;

    // Read existing nationalities data
    let mut existing: Vec<(String, i64, String, Option<String>, Option<String>)> = Vec::new();
    {
        let mut stmt = conn.prepare("SELECT name_en, count, wikidata_id, description_en, instance_of FROM nationalities")?;
        let rows = stmt.query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, i64>(1)?,
                row.get::<_, String>(2).unwrap_or_default(),
                row.get::<_, Option<String>>(3)?,
                row.get::<_, Option<String>>(4)?,
            ))
        })?;
        for r in rows {
            existing.push(r?);
        }
    }
    log(&format!("[DB] Read {} existing nationalities", existing.len()));

    // Drop and recreate with wikidata_id first
    conn.execute_batch("DROP TABLE IF EXISTS nationalities_backup;")?;
    conn.execute_batch("ALTER TABLE nationalities RENAME TO nationalities_backup;")?;

    conn.execute_batch(
        "CREATE TABLE nationalities (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            count INTEGER DEFAULT 0,
            description_en TEXT,
            instance_of TEXT,
            en_wikipedia_url TEXT,
            lat REAL,
            lon REAL,
            modern_country_name TEXT
        );"
    )?;

    let mut stmt = conn.prepare(
        "INSERT OR IGNORE INTO nationalities (wikidata_id, name_en, count, description_en, instance_of, en_wikipedia_url, lat, lon, modern_country_name)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)"
    )?;

    let pb = ProgressBar::new(existing.len() as u64);
    pb.set_style(ProgressStyle::default_bar()
        .template("{msg} [{bar:40}] {pos}/{len} ({eta})")
        .unwrap());
    pb.set_message("Inserting nationalities");

    for (name_en, count, wikidata_id, description, instance_of) in &existing {
        let wiki_url = sitelinks.get(wikidata_id).and_then(|v| v.as_str()).map(String::from);

        let (lat, lon) = if let Some(loc) = locations.get(wikidata_id) {
            (
                loc.get("lat").and_then(|v| v.as_f64()),
                loc.get("lon").and_then(|v| v.as_f64()),
            )
        } else {
            (None, None)
        };

        // Get modern_country_name
        let modern_country = nat_countries.get(wikidata_id).and_then(|v| {
            v.get("country_name").and_then(|cn| cn.as_str()).map(String::from)
        });

        stmt.execute(params![
            wikidata_id,
            name_en,
            count,
            description,
            instance_of,
            wiki_url,
            lat,
            lon,
            modern_country,
        ])?;
        pb.inc(1);
    }
    pb.finish();

    conn.execute_batch("DROP TABLE IF EXISTS nationalities_backup;")?;

    // Create indexes
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_nationalities_name ON nationalities(name_en);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_nationalities_country ON nationalities(modern_country_name);")?;

    log("[DB] 06: Done. Nationalities restructured with wikidata_id first, sitelinks, locations, and country.");
    Ok(())
}
