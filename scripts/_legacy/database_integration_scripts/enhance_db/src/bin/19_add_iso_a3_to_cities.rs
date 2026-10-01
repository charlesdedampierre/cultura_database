/// Add iso_a3 column to cities table based on matching country_name to modern_country table.
use anyhow::Result;
use rusqlite::Connection;
use std::fs;
use std::io::Write;

const DB_PATH: &str = "data/humans_clean.sqlite3";
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
    log("=== Step 19: Add iso_a3 to cities ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // Check if iso_a3 column already exists
    let has_iso: bool = {
        let mut stmt = conn.prepare("PRAGMA table_info(cities)")?;
        let cols: Vec<String> = stmt
            .query_map([], |row| row.get::<_, String>(1))?
            .filter_map(|r| r.ok())
            .collect();
        cols.contains(&"iso_a3".to_string())
    };

    if has_iso {
        log("[19] iso_a3 column already exists in cities, dropping and recreating...");
        // Recreate without it first
        conn.execute_batch(
            "CREATE TABLE cities_temp AS SELECT id, name_en, lat, lon, country_name FROM cities;
             DROP TABLE cities;
             ALTER TABLE cities_temp RENAME TO cities;"
        )?;
    }

    // Add the iso_a3 column
    log("[19] Adding iso_a3 column to cities...");
    conn.execute_batch("ALTER TABLE cities ADD COLUMN iso_a3 TEXT;")?;

    // Update iso_a3 based on country_name matching modern_country.name
    log("[19] Updating iso_a3 from modern_country table...");
    let updated = conn.execute(
        "UPDATE cities SET iso_a3 = (
            SELECT mc.iso_a3_code FROM modern_country mc WHERE mc.name = cities.country_name LIMIT 1
        ) WHERE country_name IS NOT NULL",
        [],
    )?;
    log(&format!("[19] Updated {} cities with iso_a3", updated));

    // Check results
    let total: i64 = conn.query_row("SELECT COUNT(*) FROM cities", [], |r| r.get(0))?;
    let with_iso: i64 = conn.query_row(
        "SELECT COUNT(*) FROM cities WHERE iso_a3 IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    let without_iso: i64 = conn.query_row(
        "SELECT COUNT(*) FROM cities WHERE iso_a3 IS NULL AND country_name IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    log(&format!(
        "[19] Total cities: {}, with iso_a3: {}, country_name but no iso_a3: {}",
        total, with_iso, without_iso
    ));

    // Show unmatched country names
    if without_iso > 0 {
        let mut stmt = conn.prepare(
            "SELECT DISTINCT country_name FROM cities WHERE iso_a3 IS NULL AND country_name IS NOT NULL ORDER BY country_name"
        )?;
        let unmatched: Vec<String> = stmt
            .query_map([], |r| r.get(0))?
            .filter_map(|r| r.ok())
            .collect();
        log(&format!("[19] Unmatched country names ({}):", unmatched.len()));
        for name in &unmatched {
            log(&format!("[19]   '{}'", name));
        }
    }

    // Create index
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_cities_iso_a3 ON cities(iso_a3);")?;

    // Show sample
    let mut sample = conn.prepare("SELECT id, name_en, country_name, iso_a3 FROM cities WHERE iso_a3 IS NOT NULL LIMIT 5")?;
    let rows: Vec<(String, Option<String>, Option<String>, Option<String>)> = sample
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)))?
        .filter_map(|r| r.ok())
        .collect();
    for (id, name, cn, iso) in &rows {
        log(&format!(
            "[19]   {} ({}) -> {} ({})",
            id,
            name.as_deref().unwrap_or("?"),
            cn.as_deref().unwrap_or("?"),
            iso.as_deref().unwrap_or("?")
        ));
    }

    log("=== Step 19 complete ===");
    Ok(())
}
