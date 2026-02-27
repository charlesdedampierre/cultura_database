/// Drop the individuals_regions_cliopatria table (redundant with individuals_cliopatria).
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
    log("=== Step 40: Drop individuals_regions_cliopatria ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch("DROP TABLE IF EXISTS individuals_regions_cliopatria;")?;
    log("[40] Dropped table individuals_regions_cliopatria");

    // Vacuum to reclaim space
    log("[40] Running VACUUM...");
    conn.execute_batch("VACUUM;")?;
    log("[40] VACUUM complete");

    log("=== Step 40 complete ===");
    Ok(())
}
