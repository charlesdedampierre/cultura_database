/// Remove the used_for column from properties_definition table.
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
    log("=== Step 14: Remove used_for column from properties_definition ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // Check current columns
    let mut stmt = conn.prepare("PRAGMA table_info(properties_definition)")?;
    let cols_before: Vec<String> = stmt
        .query_map([], |r| r.get::<_, String>(1))?
        .filter_map(|r| r.ok())
        .collect();
    log(&format!("[14] Current columns: {}", cols_before.join(", ")));

    if !cols_before.contains(&"used_for".to_string()) {
        log("[14] Column used_for does not exist, nothing to do.");
        return Ok(());
    }

    // Restructure to remove used_for
    log("[14] Removing used_for column...");
    conn.execute_batch(
        "ALTER TABLE properties_definition RENAME TO properties_definition_backup;

         CREATE TABLE properties_definition (
             property_id TEXT PRIMARY KEY,
             property_name TEXT,
             description TEXT,
             wikidata_url TEXT,
             table_name TEXT,
             column_name TEXT
         );

         INSERT INTO properties_definition (property_id, property_name, description, wikidata_url, table_name, column_name)
         SELECT property_id, property_name, description, wikidata_url, table_name, column_name
         FROM properties_definition_backup;

         DROP TABLE properties_definition_backup;",
    )?;

    let total: i64 = conn.query_row(
        "SELECT COUNT(*) FROM properties_definition",
        [],
        |r| r.get(0),
    )?;

    // Show new columns
    let mut stmt2 = conn.prepare("PRAGMA table_info(properties_definition)")?;
    let cols_after: Vec<String> = stmt2
        .query_map([], |r| r.get::<_, String>(1))?
        .filter_map(|r| r.ok())
        .collect();
    log(&format!(
        "[14] Properties definition: {} rows, columns: {}",
        total,
        cols_after.join(", ")
    ));

    log("=== Step 14 complete ===");
    Ok(())
}
