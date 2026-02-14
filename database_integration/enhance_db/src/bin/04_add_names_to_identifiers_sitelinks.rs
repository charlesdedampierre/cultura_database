/// Add individual name after wikidata_id in identifiers and sitelinks tables.
/// The identifiers table already has individual_name, but we ensure it's populated.
/// The sitelinks table needs a new individual_name column.
use anyhow::Result;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection};
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
    log("[DB] 04: Adding individual names to identifiers and sitelinks...");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;")?;

    // 1. Add individual_name column to sitelinks if not exists
    let sitelink_cols: Vec<String> = conn
        .prepare("PRAGMA table_info(sitelinks)")?
        .query_map([], |row| row.get::<_, String>(1))?
        .filter_map(|r| r.ok())
        .collect();

    if !sitelink_cols.contains(&"individual_name".to_string()) {
        conn.execute_batch("ALTER TABLE sitelinks ADD COLUMN individual_name TEXT;")?;
        log("[DB] Added individual_name column to sitelinks");
    }

    // 2. Update sitelinks individual_name from individuals table
    log("[DB] Updating sitelinks.individual_name from individuals...");
    // Count how many need updating
    let sitelinks_to_update: i64 = conn.query_row(
        "SELECT COUNT(*) FROM sitelinks WHERE individual_name IS NULL",
        [],
        |row| row.get(0),
    )?;
    log(&format!("[DB] Sitelinks rows to update: {}", sitelinks_to_update));

    if sitelinks_to_update > 0 {
        // Process in batches to show progress
        let batch_size: i64 = 1_000_000;
        let total_batches = (sitelinks_to_update + batch_size - 1) / batch_size;
        let pb = ProgressBar::new(total_batches as u64);
        pb.set_style(ProgressStyle::default_bar()
            .template("{msg} [{bar:40}] {pos}/{len} batches ({eta})")
            .unwrap());
        pb.set_message("Updating sitelinks names");

        for _ in 0..total_batches {
            conn.execute(
                "UPDATE sitelinks SET individual_name = (
                    SELECT individuals.name_en FROM individuals
                    WHERE individuals.wikidata_id = sitelinks.wikidata_id
                ) WHERE id IN (
                    SELECT id FROM sitelinks WHERE individual_name IS NULL LIMIT ?1
                )",
                params![batch_size],
            )?;
            pb.inc(1);
        }
        pb.finish();
    }

    // 3. Update identifiers individual_name where missing
    let ident_to_update: i64 = conn.query_row(
        "SELECT COUNT(*) FROM identifiers WHERE individual_name IS NULL OR individual_name = ''",
        [],
        |row| row.get(0),
    )?;
    log(&format!("[DB] Identifiers rows to update: {}", ident_to_update));

    if ident_to_update > 0 {
        let batch_size: i64 = 1_000_000;
        let total_batches = (ident_to_update + batch_size - 1) / batch_size;
        let pb = ProgressBar::new(total_batches as u64);
        pb.set_style(ProgressStyle::default_bar()
            .template("{msg} [{bar:40}] {pos}/{len} batches ({eta})")
            .unwrap());
        pb.set_message("Updating identifier names");

        for _ in 0..total_batches {
            conn.execute(
                "UPDATE identifiers SET individual_name = (
                    SELECT individuals.name_en FROM individuals
                    WHERE individuals.wikidata_id = identifiers.wikidata_id
                ) WHERE rowid IN (
                    SELECT rowid FROM identifiers WHERE individual_name IS NULL OR individual_name = '' LIMIT ?1
                )",
                params![batch_size],
            )?;
            pb.inc(1);
        }
        pb.finish();
    }

    log("[DB] 04: Done. Updated individual names in identifiers and sitelinks.");
    Ok(())
}
