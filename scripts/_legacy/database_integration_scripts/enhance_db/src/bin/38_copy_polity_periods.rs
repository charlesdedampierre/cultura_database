/// Copy polity_periods table from cliopatria.db to humans_clean.sqlite3
/// as cliopatria_polity_periods.
use anyhow::Result;
use rusqlite::{params, Connection};
use std::fs;
use std::io::Write;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const CLIO_DB_PATH: &str = "cliopatria_data/processing/data/cliopatria.db";
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
    log("=== Step 38: Copy polity_periods to cliopatria_polity_periods ===");

    let clio_conn = Connection::open(CLIO_DB_PATH)?;
    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // Drop and recreate
    conn.execute_batch("DROP TABLE IF EXISTS cliopatria_polity_periods;")?;
    conn.execute_batch(
        "CREATE TABLE cliopatria_polity_periods (
            id INTEGER PRIMARY KEY,
            polity_id INTEGER NOT NULL,
            polity_name TEXT,
            from_year INTEGER,
            to_year INTEGER,
            area REAL,
            geometry TEXT
        );",
    )?;

    // Read from cliopatria and insert
    let total: i64 =
        clio_conn.query_row("SELECT COUNT(*) FROM polity_periods", [], |r| r.get(0))?;
    log(&format!("[38] Total polity_periods to copy: {}", total));

    let mut stmt = clio_conn.prepare(
        "SELECT id, polity_id, polity_name, from_year, to_year, area, geometry FROM polity_periods",
    )?;
    let rows = stmt.query_map([], |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, i64>(1)?,
            r.get::<_, Option<String>>(2)?,
            r.get::<_, Option<i64>>(3)?,
            r.get::<_, Option<i64>>(4)?,
            r.get::<_, Option<f64>>(5)?,
            r.get::<_, Option<String>>(6)?,
        ))
    })?;

    conn.execute_batch("BEGIN TRANSACTION;")?;
    let mut insert = conn.prepare(
        "INSERT INTO cliopatria_polity_periods (id, polity_id, polity_name, from_year, to_year, area, geometry)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
    )?;

    let mut count = 0i64;
    for r in rows {
        let (id, polity_id, polity_name, from_year, to_year, area, geometry) = r?;
        insert.execute(params![id, polity_id, polity_name, from_year, to_year, area, geometry])?;
        count += 1;
    }
    conn.execute_batch("COMMIT;")?;

    // Create indexes
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_cpp_polity_id ON cliopatria_polity_periods(polity_id);",
    )?;
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_cpp_years ON cliopatria_polity_periods(from_year, to_year);",
    )?;

    log(&format!("[38] Copied {} rows to cliopatria_polity_periods", count));
    log("=== Step 38 complete ===");
    Ok(())
}
