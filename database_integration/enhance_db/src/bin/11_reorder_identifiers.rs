/// Reorder identifiers columns:
/// wikidata_id, individual_name, property_id, identifier_name, value, url
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
    log("=== Step 11: Reorder identifiers columns ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    let total: i64 = conn.query_row("SELECT COUNT(*) FROM identifiers", [], |r| r.get(0))?;
    log(&format!("[11] Identifiers table has {} rows", total));

    log("[11] Restructuring identifiers (reordering columns)...");
    conn.execute_batch(
        "ALTER TABLE identifiers RENAME TO identifiers_backup;

         CREATE TABLE identifiers (
             wikidata_id TEXT,
             individual_name TEXT,
             property_id TEXT,
             identifier_name TEXT,
             value TEXT,
             url TEXT,
             PRIMARY KEY (wikidata_id, property_id, value)
         );

         INSERT INTO identifiers (wikidata_id, individual_name, property_id, identifier_name, value, url)
         SELECT wikidata_id, individual_name, property_id, identifier_name, value, url
         FROM identifiers_backup;

         DROP TABLE identifiers_backup;",
    )?;

    // Recreate indexes
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_identifiers_wikidata ON identifiers(wikidata_id);
         CREATE INDEX IF NOT EXISTS idx_identifiers_property ON identifiers(property_id);
         CREATE INDEX IF NOT EXISTS idx_identifiers_name ON identifiers(individual_name);",
    )?;

    let verify: i64 = conn.query_row("SELECT COUNT(*) FROM identifiers", [], |r| r.get(0))?;
    log(&format!("[11] Identifiers after restructure: {} rows", verify));

    // Show column order
    let mut stmt = conn.prepare("PRAGMA table_info(identifiers)")?;
    let cols: Vec<String> = stmt
        .query_map([], |r| r.get::<_, String>(1))?
        .filter_map(|r| r.ok())
        .collect();
    log(&format!("[11] Column order: {}", cols.join(", ")));

    log("=== Step 11 complete ===");
    Ok(())
}
