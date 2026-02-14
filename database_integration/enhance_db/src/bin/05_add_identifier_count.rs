/// Add identifiers_count column to individuals table.
/// Counts the number of identifiers per individual.
use anyhow::Result;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::Connection;
use std::fs;
use std::io::Write;

const DB_PATH: &str = "data/humans_clean.sqlite3";
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
    log("[DB] 05: Adding identifiers_count to individuals...");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;")?;

    // Add column if not exists
    let columns: Vec<String> = conn
        .prepare("PRAGMA table_info(individuals)")?
        .query_map([], |row| row.get::<_, String>(1))?
        .filter_map(|r| r.ok())
        .collect();

    if !columns.contains(&"identifiers_count".to_string()) {
        conn.execute_batch("ALTER TABLE individuals ADD COLUMN identifiers_count INTEGER DEFAULT 0;")?;
        log("[DB] Added identifiers_count column");
    }

    // Count identifiers per individual
    log("[DB] Computing identifier counts...");

    let pb = ProgressBar::new_spinner();
    pb.set_style(ProgressStyle::default_spinner()
        .template("{msg} {spinner} {elapsed}")
        .unwrap());
    pb.set_message("Computing identifier counts");
    pb.enable_steady_tick(std::time::Duration::from_millis(200));

    conn.execute_batch(
        "UPDATE individuals SET identifiers_count = (
            SELECT COUNT(*) FROM identifiers WHERE identifiers.wikidata_id = individuals.wikidata_id
        );"
    )?;

    pb.finish_with_message("Identifier counts computed");

    // Show some stats
    let total: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals WHERE identifiers_count > 0",
        [],
        |row| row.get(0),
    )?;
    let max_count: i64 = conn.query_row(
        "SELECT MAX(identifiers_count) FROM individuals",
        [],
        |row| row.get(0),
    )?;
    let avg_count: f64 = conn.query_row(
        "SELECT AVG(identifiers_count) FROM individuals WHERE identifiers_count > 0",
        [],
        |row| row.get(0),
    )?;

    log(&format!("[DB] Individuals with identifiers: {}", total));
    log(&format!("[DB] Max identifiers per individual: {}", max_count));
    log(&format!("[DB] Avg identifiers (for those with any): {:.1}", avg_count));

    log("[DB] 05: Done.");
    Ok(())
}
