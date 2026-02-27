/// Fix nationalities table:
/// - Remove modern_country_name column
/// - Add country_name and iso_a3_code from reverse geocoding results
use anyhow::Result;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection};
use serde_json::Value;
use std::collections::HashMap;
use std::fs;
use std::io::Write;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const GEOCODED_PATH: &str = "data/all_humans/nationality_modern_countries.json";
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
    log("=== Step 18: Fix nationalities - replace modern_country_name with country_name + iso_a3_code ===");

    // Load geocoded data
    log("[18] Loading reverse geocoded nationality countries...");
    let geocoded_json = fs::read_to_string(GEOCODED_PATH)?;
    let geocoded: HashMap<String, Value> = serde_json::from_str(&geocoded_json)?;
    log(&format!("[18] Loaded {} geocoded entries", geocoded.len()));

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // Read existing nationalities
    log("[18] Reading existing nationalities...");
    let mut existing: Vec<(String, Option<String>, i64, Option<String>, Option<String>, Option<String>, Option<f64>, Option<f64>)> = Vec::new();
    {
        let mut stmt = conn.prepare(
            "SELECT wikidata_id, name_en, count, description_en, instance_of, en_wikipedia_url, lat, lon FROM nationalities"
        )?;
        let rows = stmt.query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, Option<String>>(1)?,
                row.get::<_, i64>(2)?,
                row.get::<_, Option<String>>(3)?,
                row.get::<_, Option<String>>(4)?,
                row.get::<_, Option<String>>(5)?,
                row.get::<_, Option<f64>>(6)?,
                row.get::<_, Option<f64>>(7)?,
            ))
        })?;
        for r in rows {
            existing.push(r?);
        }
    }
    log(&format!("[18] Read {} nationalities", existing.len()));

    // Recreate table without modern_country_name, with country_name and iso_a3_code
    log("[18] Recreating nationalities table with new schema...");
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
            country_name TEXT,
            iso_a3_code TEXT
        );"
    )?;

    let mut stmt = conn.prepare(
        "INSERT INTO nationalities (wikidata_id, name_en, count, description_en, instance_of, en_wikipedia_url, lat, lon, country_name, iso_a3_code)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)"
    )?;

    let pb = ProgressBar::new(existing.len() as u64);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{msg} [{bar:40}] {pos}/{len} ({eta})")
            .unwrap(),
    );
    pb.set_message("Inserting nationalities");

    let mut mapped_count = 0;
    let mut unmapped_count = 0;

    for (wikidata_id, name_en, count, description, instance_of, wiki_url, lat, lon) in &existing {
        let (country_name, iso_a3_code) = if let Some(geo) = geocoded.get(wikidata_id) {
            let cn = geo.get("country_name").and_then(|v| v.as_str()).map(String::from);
            let iso = geo.get("iso_a3_code").and_then(|v| v.as_str()).map(String::from);
            if cn.is_some() {
                mapped_count += 1;
            }
            (cn, iso)
        } else {
            unmapped_count += 1;
            (None, None)
        };

        stmt.execute(params![
            wikidata_id,
            name_en,
            count,
            description,
            instance_of,
            wiki_url,
            lat,
            lon,
            country_name,
            iso_a3_code,
        ])?;
        pb.inc(1);
    }
    pb.finish();

    conn.execute_batch("DROP TABLE IF EXISTS nationalities_backup;")?;

    // Create indexes
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_nationalities_name ON nationalities(name_en);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_nationalities_country ON nationalities(country_name);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_nationalities_iso ON nationalities(iso_a3_code);")?;

    log(&format!("[18] Mapped: {}, Unmapped (no lat/lon): {}", mapped_count, unmapped_count));

    // Show some examples
    let mut check = conn.prepare("SELECT wikidata_id, name_en, country_name, iso_a3_code FROM nationalities WHERE country_name IS NOT NULL LIMIT 10")?;
    let rows: Vec<(String, Option<String>, Option<String>, Option<String>)> = check
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)))?
        .filter_map(|r| r.ok())
        .collect();
    for (wid, name, cn, iso) in &rows {
        log(&format!("[18]   {} ({}) -> {} ({})", wid, name.as_deref().unwrap_or("?"), cn.as_deref().unwrap_or("?"), iso.as_deref().unwrap_or("?")));
    }

    let total: i64 = conn.query_row("SELECT COUNT(*) FROM nationalities", [], |r| r.get(0))?;
    let with_country: i64 = conn.query_row("SELECT COUNT(*) FROM nationalities WHERE country_name IS NOT NULL", [], |r| r.get(0))?;
    log(&format!("[18] Total nationalities: {}, with country: {}", total, with_country));

    log("=== Step 18 complete ===");
    Ok(())
}
