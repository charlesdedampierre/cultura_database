/// Fix modern_country table: compute count from nationalities, order by count DESC.
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
    log("=== Step 13: Fix modern_country count and order ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // Compute count: sum of nationality counts per modern country
    log("[13] Computing modern_country counts from nationalities...");
    conn.execute_batch(
        "UPDATE modern_country SET count = COALESCE(
           (SELECT SUM(count) FROM nationalities
            WHERE modern_country_name = modern_country.name), 0);",
    )?;

    let nonzero: i64 = conn.query_row(
        "SELECT COUNT(*) FROM modern_country WHERE count > 0",
        [],
        |r| r.get(0),
    )?;
    log(&format!(
        "[13]   {} modern countries with non-zero count",
        nonzero
    ));

    // Reorder by count DESC
    log("[13] Reordering modern_country by count DESC...");
    conn.execute_batch(
        "ALTER TABLE modern_country RENAME TO modern_country_backup;

         CREATE TABLE modern_country (
             id TEXT PRIMARY KEY,
             name TEXT NOT NULL,
             continent TEXT,
             iso_a3_code TEXT NOT NULL,
             en_wikipedia_url TEXT,
             count INTEGER DEFAULT 0
         );

         INSERT INTO modern_country (id, name, continent, iso_a3_code, en_wikipedia_url, count)
         SELECT id, name, continent, iso_a3_code, en_wikipedia_url, count
         FROM modern_country_backup
         ORDER BY count DESC;

         DROP TABLE modern_country_backup;",
    )?;

    let total: i64 = conn.query_row("SELECT COUNT(*) FROM modern_country", [], |r| r.get(0))?;
    log(&format!("[13] modern_country: {} rows", total));

    // Show top 10
    let mut stmt = conn.prepare("SELECT name, count FROM modern_country LIMIT 10")?;
    let rows: Vec<(String, i64)> = stmt
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
        .filter_map(|r| r.ok())
        .collect();
    for (name, count) in &rows {
        log(&format!("[13]   {} ({})", name, count));
    }

    log("=== Step 13 complete ===");
    Ok(())
}
