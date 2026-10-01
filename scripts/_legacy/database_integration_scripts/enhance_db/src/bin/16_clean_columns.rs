/// Remove unnecessary columns from cities, occupations, and properties_definition tables.
/// - cities: remove `count` column
/// - occupations: remove `instance_of_id` and `instance_of` columns
/// - properties_definition: remove `wikidata_url` column
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
    log("=== Step 16: Clean columns from cities, occupations, properties_definition ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // 1. Remove count from cities
    log("[16] Removing 'count' from cities...");
    conn.execute("DROP INDEX IF EXISTS idx_cities_count", [])?;
    conn.execute_batch("ALTER TABLE cities DROP COLUMN count;")?;
    let city_count: i64 = conn.query_row("SELECT COUNT(*) FROM cities", [], |r| r.get(0))?;
    log(&format!("[16] Cities: {} rows, count column removed", city_count));

    // 2. Remove instance_of_id and instance_of from occupations
    log("[16] Removing 'instance_of_id' and 'instance_of' from occupations...");
    conn.execute_batch("ALTER TABLE occupations DROP COLUMN instance_of_id;")?;
    conn.execute_batch("ALTER TABLE occupations DROP COLUMN instance_of;")?;
    let occ_count: i64 = conn.query_row("SELECT COUNT(*) FROM occupations", [], |r| r.get(0))?;
    log(&format!("[16] Occupations: {} rows, instance_of columns removed", occ_count));

    // 3. Remove wikidata_url from properties_definition
    log("[16] Removing 'wikidata_url' from properties_definition...");
    conn.execute_batch("ALTER TABLE properties_definition DROP COLUMN wikidata_url;")?;
    let prop_count: i64 = conn.query_row("SELECT COUNT(*) FROM properties_definition", [], |r| r.get(0))?;
    log(&format!("[16] Properties definition: {} rows, wikidata_url removed", prop_count));

    log("=== Step 16 complete ===");
    Ok(())
}
