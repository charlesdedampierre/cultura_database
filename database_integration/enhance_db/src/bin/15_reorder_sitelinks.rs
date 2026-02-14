/// Reorder sitelinks columns: id, wikidata_id, individual_name, site, title, url
use anyhow::Result;
use rusqlite::Connection;
use std::fs;
use std::io::Write;
use std::time::Instant;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const TASK_LOG: &str = "task.log";

fn log(msg: &str) {
    let now = chrono_now();
    let line = format!("[{}] {}", now, msg);
    println!("{}", line);
    let mut f = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(TASK_LOG)
        .unwrap();
    writeln!(f, "{}", line).unwrap();
}

fn chrono_now() -> String {
    let dur = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap();
    let secs = dur.as_secs();
    let hours = (secs % 86400) / 3600;
    let mins = (secs % 3600) / 60;
    let s = secs % 60;
    format!("{:02}:{:02}:{:02} UTC", hours, mins, s)
}

fn elapsed(start: Instant) -> String {
    let d = start.elapsed();
    let secs = d.as_secs();
    if secs < 60 {
        format!("{}s", secs)
    } else if secs < 3600 {
        format!("{}m {}s", secs / 60, secs % 60)
    } else {
        format!("{}h {}m {}s", secs / 3600, (secs % 3600) / 60, secs % 60)
    }
}

fn main() -> Result<()> {
    let total_start = Instant::now();
    log("=== Step 15: Reorder sitelinks columns ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    let total: i64 = conn.query_row("SELECT COUNT(*) FROM sitelinks", [], |r| r.get(0))?;
    log(&format!("[15] Sitelinks table has {} rows", total));

    let mut stmt = conn.prepare("PRAGMA table_info(sitelinks)")?;
    let cols_before: Vec<String> = stmt
        .query_map([], |r| r.get::<_, String>(1))?
        .filter_map(|r| r.ok())
        .collect();
    log(&format!("[15] Current columns: {}", cols_before.join(", ")));

    let step = Instant::now();
    log("[15] Restructuring sitelinks (moving individual_name after wikidata_id)...");

    conn.execute_batch("ALTER TABLE sitelinks RENAME TO sitelinks_backup;")?;
    log(&format!("[15]   Renamed to backup ({})", elapsed(step)));

    conn.execute_batch(
        "CREATE TABLE sitelinks (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             wikidata_id TEXT NOT NULL,
             individual_name TEXT,
             site TEXT,
             title TEXT,
             url TEXT
         );",
    )?;

    log("[15]   Inserting data...");
    let step = Instant::now();
    conn.execute_batch(
        "INSERT INTO sitelinks (id, wikidata_id, individual_name, site, title, url)
         SELECT id, wikidata_id, individual_name, site, title, url
         FROM sitelinks_backup;",
    )?;
    log(&format!("[15]   INSERT complete ({} for {} rows)", elapsed(step), total));

    let step = Instant::now();
    conn.execute_batch("DROP TABLE sitelinks_backup;")?;
    log(&format!("[15]   Backup dropped ({})", elapsed(step)));

    // Recreate index
    let step = Instant::now();
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_sitelinks_wikidata ON sitelinks(wikidata_id);",
    )?;
    log(&format!("[15]   Index created ({})", elapsed(step)));

    let verify: i64 = conn.query_row("SELECT COUNT(*) FROM sitelinks", [], |r| r.get(0))?;
    log(&format!("[15] Sitelinks after restructure: {} rows", verify));

    let mut stmt2 = conn.prepare("PRAGMA table_info(sitelinks)")?;
    let cols_after: Vec<String> = stmt2
        .query_map([], |r| r.get::<_, String>(1))?
        .filter_map(|r| r.ok())
        .collect();
    log(&format!("[15] New columns: {}", cols_after.join(", ")));

    log(&format!(
        "=== Step 15 complete (total: {}) ===",
        elapsed(total_start)
    ));
    Ok(())
}
