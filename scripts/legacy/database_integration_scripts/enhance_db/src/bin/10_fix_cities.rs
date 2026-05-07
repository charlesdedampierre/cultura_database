/// Fix cities table: reorder by count DESC.
/// Columns are already restructured and counts are populated.
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
    log("=== Step 10: Reorder cities by count DESC ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    let total: i64 = conn.query_row("SELECT COUNT(*) FROM cities", [], |r| r.get(0))?;
    log(&format!("[10] Cities table: {} rows", total));

    // Check current ordering
    let first: i64 = conn.query_row("SELECT count FROM cities LIMIT 1", [], |r| r.get(0))?;
    log(&format!("[10] Current first row count: {}", first));

    // Remove unwanted columns and reorder by count DESC
    log("[10] Removing iso_a3, country_id, continent_id, continent and reordering by count DESC...");
    conn.execute_batch(
        "ALTER TABLE cities RENAME TO cities_backup;

         CREATE TABLE cities (
             id TEXT PRIMARY KEY,
             name_en TEXT,
             lat REAL,
             lon REAL,
             country_name TEXT,
             count INTEGER DEFAULT 0
         );

         INSERT INTO cities (id, name_en, lat, lon, country_name, count)
         SELECT id, name_en, lat, lon, country_name, count
         FROM cities_backup
         ORDER BY count DESC;

         DROP TABLE cities_backup;",
    )?;

    // Recreate indexes
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_cities_name ON cities(name_en);
         CREATE INDEX IF NOT EXISTS idx_cities_count ON cities(count);
         CREATE INDEX IF NOT EXISTS idx_cities_country ON cities(country_name);",
    )?;

    let new_first: i64 = conn.query_row("SELECT count FROM cities LIMIT 1", [], |r| r.get(0))?;
    log(&format!("[10] New first row count: {} (should be highest)", new_first));

    let mut stmt = conn.prepare("SELECT name_en, count FROM cities LIMIT 5")?;
    let rows: Vec<(String, i64)> = stmt
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
        .filter_map(|r| r.ok())
        .collect();
    for (name, count) in &rows {
        log(&format!("[10]   {} ({})", name, count));
    }

    log("=== Step 10 complete ===");
    Ok(())
}
