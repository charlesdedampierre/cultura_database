/// Remove individuals_count column from polities_cliopatria (keep number_individuals).
/// SQLite 3.35.0+ supports ALTER TABLE DROP COLUMN (rusqlite 0.31 bundles 3.45+).
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
    let _ = fs::remove_file(TASK_LOG);
    log("=== Step 54: Remove individuals_count from polities_cliopatria (keep number_individuals) ===");

    let conn = Connection::open(DB_PATH)?;

    // Check current schema
    let schema: String = conn.query_row(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='polities_cliopatria'",
        [],
        |r| r.get(0),
    )?;
    log(&format!("[54] Current schema: {}", schema));

    // Drop individuals_count column only
    log("[54] Dropping column individuals_count...");
    conn.execute_batch("ALTER TABLE polities_cliopatria DROP COLUMN individuals_count;")?;
    log("[54] Dropped individuals_count (kept number_individuals)");

    // Verify new schema
    let new_schema: String = conn.query_row(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='polities_cliopatria'",
        [],
        |r| r.get(0),
    )?;
    log(&format!("[54] New schema: {}", new_schema));

    let row_count: i64 = conn.query_row(
        "SELECT COUNT(*) FROM polities_cliopatria",
        [],
        |r| r.get(0),
    )?;
    log(&format!("[54] polities_cliopatria row count: {}", row_count));

    log("=== Step 54 complete ===");
    Ok(())
}
