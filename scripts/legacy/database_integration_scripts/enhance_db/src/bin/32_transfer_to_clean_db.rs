/// Transfer all tables from corrupted database to a fresh clean database.
/// Uses ATTACH DATABASE + INSERT INTO ... SELECT for maximum speed (data stays in SQLite engine).
use anyhow::Result;
use rusqlite::Connection;
use std::fs;
use std::io::Write;
use std::time::Instant;

const SRC_DB: &str = "/workspace/data/humans_clean.sqlite3";
const DST_DB: &str = "/workspace/data/humans_clean_new.sqlite3";

fn log(msg: &str) {
    let dur = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap();
    let secs = dur.as_secs();
    let ts = format!(
        "{:02}:{:02}:{:02}",
        (secs % 86400) / 3600,
        (secs % 3600) / 60,
        secs % 60
    );
    let line = format!("[{}] {}", ts, msg);
    println!("{}", line);
    if let Ok(mut f) = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open("/workspace/transfer.log")
    {
        let _ = writeln!(f, "{}", line);
    }
}

fn elapsed(start: Instant) -> String {
    let s = start.elapsed().as_secs();
    if s < 60 {
        format!("{}s", s)
    } else if s < 3600 {
        format!("{}m {}s", s / 60, s % 60)
    } else {
        format!("{}h {}m {}s", s / 3600, (s % 3600) / 60, s % 60)
    }
}

fn main() -> Result<()> {
    let total_start = Instant::now();
    log("=== TRANSFER: Copying all tables to clean database ===");
    log(&format!("Source: {}", SRC_DB));
    log(&format!("Destination: {}", DST_DB));

    // Remove destination if it exists (fresh start)
    if fs::metadata(DST_DB).is_ok() {
        fs::remove_file(DST_DB)?;
        log("Removed existing destination database");
    }

    // Open source database
    let conn = Connection::open(SRC_DB)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL;
         PRAGMA synchronous=NORMAL;
         PRAGMA cache_size=-4000000;
         PRAGMA busy_timeout=60000;
         PRAGMA mmap_size=8589934592;",
    )?;

    // Attach the new clean database
    conn.execute_batch(&format!("ATTACH DATABASE '{}' AS clean;", DST_DB))?;
    conn.execute_batch(
        "PRAGMA clean.journal_mode=WAL;
         PRAGMA clean.synchronous=OFF;
         PRAGMA clean.cache_size=-4000000;",
    )?;
    log("Attached clean database");

    // Get all table creation SQL and index SQL from source
    let mut stmt = conn.prepare(
        "SELECT type, name, sql FROM main.sqlite_master
         WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
         ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END, name",
    )?;

    let objects: Vec<(String, String, String)> = stmt
        .query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
            ))
        })?
        .filter_map(|r| r.ok())
        .collect();

    let tables: Vec<&(String, String, String)> =
        objects.iter().filter(|(t, _, _)| t == "table").collect();
    let indexes: Vec<&(String, String, String)> =
        objects.iter().filter(|(t, _, _)| t == "index").collect();

    log(&format!(
        "Found {} tables and {} indexes to transfer",
        tables.len(),
        indexes.len()
    ));

    // Phase 1: Create tables and copy data
    log("--- Phase 1: Creating tables and copying data ---");
    for (_, name, create_sql) in &tables {
        let step_start = Instant::now();

        // Create table in clean database (replace implicit "main." with "clean.")
        let clean_sql = create_sql.replace("CREATE TABLE ", "CREATE TABLE clean.");
        let clean_sql = clean_sql.replace("CREATE TABLE clean.clean.", "CREATE TABLE clean.");
        conn.execute_batch(&clean_sql)?;

        // Copy data
        let copy_sql = format!(
            "INSERT INTO clean.\"{}\" SELECT * FROM main.\"{}\"",
            name, name
        );
        let copied = conn.execute(&copy_sql, [])?;

        log(&format!(
            "  {} : {} rows copied ({})",
            name,
            copied,
            elapsed(step_start)
        ));
    }

    // Phase 2: Create indexes
    log("--- Phase 2: Creating indexes ---");
    for (_, name, create_sql) in &indexes {
        let step_start = Instant::now();

        // Rewrite index SQL to target clean database
        let clean_sql = create_sql
            .replace("CREATE INDEX ", "CREATE INDEX clean.")
            .replace("CREATE UNIQUE INDEX ", "CREATE UNIQUE INDEX clean.");
        // Fix double-prefixed clean.clean.
        let clean_sql = clean_sql
            .replace("clean.clean.", "clean.");

        match conn.execute_batch(&clean_sql) {
            Ok(_) => log(&format!("  Index {} created ({})", name, elapsed(step_start))),
            Err(e) => log(&format!("  Index {} FAILED: {} ({})", name, e, elapsed(step_start))),
        }
    }

    // Phase 3: Verify
    log("--- Phase 3: Verification ---");
    for (_, name, _) in &tables {
        let src_count: i64 = conn
            .query_row(
                &format!("SELECT COUNT(*) FROM main.\"{}\"", name),
                [],
                |r| r.get(0),
            )
            .unwrap_or(-1);
        let dst_count: i64 = conn
            .query_row(
                &format!("SELECT COUNT(*) FROM clean.\"{}\"", name),
                [],
                |r| r.get(0),
            )
            .unwrap_or(-1);
        let status = if src_count == dst_count { "OK" } else { "MISMATCH!" };
        log(&format!(
            "  {} : src={} dst={} [{}]",
            name, src_count, dst_count, status
        ));
    }

    // Detach and set final pragmas on new DB
    conn.execute_batch("DETACH DATABASE clean;")?;

    // Open the new DB directly to finalize
    let new_conn = Connection::open(DST_DB)?;
    new_conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA integrity_check;")?;
    let integrity: String = new_conn.query_row("PRAGMA integrity_check;", [], |r| r.get(0))?;
    log(&format!("New database integrity: {}", integrity));

    log(&format!(
        "=== TRANSFER COMPLETE ({}) ===",
        elapsed(total_start)
    ));
    log(&format!("Clean database at: {}", DST_DB));

    Ok(())
}
