/// Create modern_country table from extracted JSON data.
/// Also updates cities table to reference modern_country_name.
use anyhow::Result;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection};
use serde_json::Value;
use std::collections::HashMap;
use std::fs;
use std::io::Write;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const JSON_PATH: &str = "data/all_humans/modern_countries.json";
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
    log("[DB] 01: Creating modern_country table...");

    let json_str = fs::read_to_string(JSON_PATH)?;
    let countries: HashMap<String, Value> = serde_json::from_str(&json_str)?;

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;")?;

    // Drop existing table if any
    conn.execute_batch("DROP TABLE IF EXISTS modern_country;")?;

    // Create modern_country table
    conn.execute_batch(
        "CREATE TABLE modern_country (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            continent TEXT,
            iso_a3_code TEXT NOT NULL,
            en_wikipedia_url TEXT,
            count INTEGER DEFAULT 0
        );"
    )?;

    let mut stmt = conn.prepare(
        "INSERT OR IGNORE INTO modern_country (id, name, continent, iso_a3_code, en_wikipedia_url)
         VALUES (?1, ?2, ?3, ?4, ?5)"
    )?;

    let pb = ProgressBar::new(countries.len() as u64);
    pb.set_style(ProgressStyle::default_bar()
        .template("{msg} [{bar:40}] {pos}/{len} ({eta})")
        .unwrap());
    pb.set_message("Inserting countries");

    let mut inserted = 0u64;
    for (_qid, val) in &countries {
        let id = val["id"].as_str().unwrap_or_default();
        let name = val["name"].as_str().unwrap_or_default();
        let continent = val["continent"].as_str();
        let iso3 = val["iso_a3_code"].as_str().unwrap_or_default();
        let wiki_url = val["en_wikipedia_url"].as_str();

        if !iso3.is_empty() {
            stmt.execute(params![id, name, continent, iso3, wiki_url])?;
            inserted += 1;
        }
        pb.inc(1);
    }
    pb.finish();

    // Build a lookup: country_id -> country_name from modern_country
    let mut country_lookup: HashMap<String, String> = HashMap::new();
    {
        let mut q = conn.prepare("SELECT id, name FROM modern_country")?;
        let rows = q.query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        })?;
        for r in rows {
            let (id, name) = r?;
            country_lookup.insert(id, name);
        }
    }

    // Also build lookup by iso_a3 and name for cities table matching
    let mut iso3_lookup: HashMap<String, String> = HashMap::new();
    let mut name_lookup: HashMap<String, String> = HashMap::new();
    {
        let mut q = conn.prepare("SELECT id, name, iso_a3_code FROM modern_country")?;
        let rows = q.query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
            ))
        })?;
        for r in rows {
            let (id, name, iso3) = r?;
            iso3_lookup.insert(iso3, name.clone());
            name_lookup.insert(name, id);
        }
    }

    // Update cities table: ensure country_name matches modern_country name
    // The cities table already has country_id and country_name columns
    // We update country_name to match the modern_country name if the country_id exists
    log("[DB] Updating cities table with modern_country_name...");
    let updated = conn.execute(
        "UPDATE cities SET country_name = (
            SELECT modern_country.name FROM modern_country WHERE modern_country.id = cities.country_id
        ) WHERE country_id IN (SELECT id FROM modern_country)",
        [],
    )?;
    log(&format!("[DB] Updated {} city rows with modern_country_name", updated));

    // Update count in modern_country from individuals nationalities
    // Count how many individuals have each country as nationality (via cities or nationality_countries mapping)
    log("[DB] Computing country counts from cities...");
    conn.execute_batch(
        "UPDATE modern_country SET count = (
            SELECT COALESCE(SUM(cities.count), 0) FROM cities WHERE cities.country_id = modern_country.id
        );"
    )?;

    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_modern_country_iso3 ON modern_country(iso_a3_code);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_modern_country_name ON modern_country(name);")?;

    log(&format!("[DB] 01: Done. Inserted {} modern countries.", inserted));
    Ok(())
}
