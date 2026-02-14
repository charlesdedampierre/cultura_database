/// Add gender column to individuals table.
/// Reads from pre-processed TSV file (wikidata_id\tgender) to avoid OOM.
use anyhow::Result;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection};
use std::fs;
use std::io::{BufRead, BufReader, Write};

const DB_PATH: &str = "data/humans_clean.sqlite3";
const TSV_PATH: &str = "data/all_humans/all_human_genders.tsv";
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
    log("[DB] 03: Adding gender column to individuals...");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-500000;")?;

    // Add gender column if it doesn't exist
    let columns: Vec<String> = conn
        .prepare("PRAGMA table_info(individuals)")?
        .query_map([], |row| row.get::<_, String>(1))?
        .filter_map(|r| r.ok())
        .collect();

    if !columns.contains(&"gender".to_string()) {
        conn.execute_batch("ALTER TABLE individuals ADD COLUMN gender TEXT;")?;
        log("[DB] Added gender column to individuals");
    } else {
        log("[DB] gender column already exists");
    }

    // Count lines for progress bar
    let file = fs::File::open(TSV_PATH)?;
    let file_size = file.metadata()?.len();

    let pb = ProgressBar::new(file_size);
    pb.set_style(ProgressStyle::default_bar()
        .template("{msg} [{bar:40}] {bytes}/{total_bytes} ({bytes_per_sec}) ({eta})")
        .unwrap());
    pb.set_message("Setting gender");

    let file = fs::File::open(TSV_PATH)?;
    let reader = BufReader::with_capacity(16 * 1024 * 1024, file);

    conn.execute_batch("BEGIN TRANSACTION;")?;
    let mut stmt = conn.prepare("UPDATE individuals SET gender = ?1 WHERE wikidata_id = ?2")?;

    let mut updated = 0u64;
    let mut bytes_read = 0u64;

    for line in reader.lines() {
        let line = line?;
        bytes_read += line.len() as u64 + 1;

        if line.starts_with("wikidata_id") {
            continue; // Skip header
        }

        let parts: Vec<&str> = line.splitn(2, '\t').collect();
        if parts.len() >= 2 {
            let wikidata_id = parts[0];
            let gender = parts[1];

            if !gender.is_empty() {
                stmt.execute(params![gender, wikidata_id])?;
                updated += 1;
            }
        }

        if updated % 500_000 == 0 && updated > 0 {
            conn.execute_batch("COMMIT; BEGIN TRANSACTION;")?;
            stmt = conn.prepare("UPDATE individuals SET gender = ?1 WHERE wikidata_id = ?2")?;
            pb.set_position(bytes_read);
            log(&format!("[DB]   Processed {} entries...", updated));
        }

        if updated % 100_000 == 0 {
            pb.set_position(bytes_read);
        }
    }

    conn.execute_batch("COMMIT;")?;
    pb.finish();

    log(&format!("[DB] 03: Done. Updated {} individuals with gender.", updated));
    Ok(())
}
