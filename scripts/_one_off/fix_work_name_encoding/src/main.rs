// Repair mojibake in works.work_name (humans_clean.sqlite3).
//
// The corruption pattern is the classic "UTF-8 bytes interpreted as Latin-1
// then re-encoded as UTF-8". Recovery: take each codepoint of the broken
// string, if it fits in a byte (<= 0xFF) collect it as a Latin-1 byte, then
// decode the byte sequence as UTF-8. If either step fails, leave the row
// untouched (string is already correct or genuinely broken in a different way).
//
// Reads all rows where work_name is non-ASCII (LENGTH(text) != LENGTH(blob)),
// streams them in chunks, applies the fix, and batch-updates only the rows
// whose value actually changed.

use anyhow::{Context, Result};
use chrono::Local;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection, OpenFlags};
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::time::Instant;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const LOG_PATH: &str = "logs/fix_work_name_encoding.log";
const READ_CHUNK: usize = 50_000;
const WRITE_BATCH: usize = 10_000;

fn log_line(log: &mut std::fs::File, msg: &str) {
    let stamped = format!("[{}] {}", Local::now().format("%Y-%m-%d %H:%M:%S"), msg);
    println!("{stamped}");
    let _ = writeln!(log, "{stamped}");
    let _ = log.flush();
}

/// Try to repair mojibake. Returns Some(fixed) only if it differs from input.
fn try_repair(s: &str) -> Option<String> {
    let mut bytes = Vec::with_capacity(s.len());
    for ch in s.chars() {
        let cp = ch as u32;
        if cp > 0xFF {
            return None; // not Latin-1, almost certainly already-correct UTF-8
        }
        bytes.push(cp as u8);
    }
    let fixed = std::str::from_utf8(&bytes).ok()?;
    if fixed == s {
        None
    } else {
        Some(fixed.to_string())
    }
}

fn main() -> Result<()> {
    if !Path::new(DB_PATH).exists() {
        anyhow::bail!(
            "DB not found at {DB_PATH}. Run from project root (cultura_database/)."
        );
    }
    std::fs::create_dir_all("logs").ok();
    let mut log = OpenOptions::new()
        .create(true)
        .append(true)
        .open(LOG_PATH)
        .with_context(|| format!("opening log {LOG_PATH}"))?;

    log_line(&mut log, "=== fix_work_name_encoding START ===");

    let conn = Connection::open_with_flags(
        DB_PATH,
        OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .with_context(|| format!("opening {DB_PATH}"))?;

    conn.pragma_update(None, "journal_mode", "WAL")?;
    conn.pragma_update(None, "synchronous", "NORMAL")?;
    conn.pragma_update(None, "temp_store", "MEMORY")?;
    conn.pragma_update(None, "cache_size", -1_000_000)?; // ~1 GiB page cache

    // Universe of candidate rows: any work_name with non-ASCII bytes.
    let total: i64 = conn.query_row(
        "SELECT COUNT(*) FROM works
         WHERE work_name IS NOT NULL AND work_name != ''
           AND LENGTH(work_name) != LENGTH(CAST(work_name AS BLOB))",
        [],
        |r| r.get(0),
    )?;
    log_line(
        &mut log,
        &format!("Candidate rows (non-ASCII work_name): {total}"),
    );

    let pb = ProgressBar::new(total as u64);
    pb.set_style(
        ProgressStyle::with_template(
            "{spinner} {pos}/{len} ({percent}%) | fixed={msg} | ETA {eta}",
        )
        .unwrap(),
    );
    pb.set_message("0");

    let mut select = conn.prepare(
        "SELECT id, work_name FROM works
         WHERE work_name IS NOT NULL AND work_name != ''
           AND LENGTH(work_name) != LENGTH(CAST(work_name AS BLOB))
           AND id > ?1
         ORDER BY id
         LIMIT ?2",
    )?;

    let mut last_id: i64 = 0;
    let mut scanned: u64 = 0;
    let mut fixed_total: u64 = 0;
    let mut pending: Vec<(String, i64)> = Vec::with_capacity(WRITE_BATCH);
    let started = Instant::now();

    // Open one transaction; flush every WRITE_BATCH rows.
    let mut tx_open = false;

    loop {
        let mut rows = select.query(params![last_id, READ_CHUNK as i64])?;
        let mut got = 0usize;
        let mut chunk_last_id = last_id;
        while let Some(row) = rows.next()? {
            let id: i64 = row.get(0)?;
            let name: String = row.get(1)?;
            chunk_last_id = id;
            got += 1;

            if let Some(fixed) = try_repair(&name) {
                pending.push((fixed, id));
            }

            // Flush when batch is full.
            if pending.len() >= WRITE_BATCH {
                if !tx_open {
                    conn.execute_batch("BEGIN IMMEDIATE")?;
                    tx_open = true;
                }
                let mut update = conn.prepare_cached(
                    "UPDATE works SET work_name = ?1 WHERE id = ?2",
                )?;
                for (val, id) in pending.drain(..) {
                    update.execute(params![val, id])?;
                    fixed_total += 1;
                }
                conn.execute_batch("COMMIT")?;
                tx_open = false;
            }
        }
        scanned += got as u64;
        pb.set_position(scanned);
        pb.set_message(fixed_total.to_string());

        if got == 0 {
            break;
        }
        last_id = chunk_last_id;

        // Periodic log line every ~500k rows
        if scanned % 500_000 < READ_CHUNK as u64 {
            log_line(
                &mut log,
                &format!("scanned={scanned} fixed={fixed_total} last_id={last_id}"),
            );
        }
    }

    // Final flush.
    if !pending.is_empty() {
        if !tx_open {
            conn.execute_batch("BEGIN IMMEDIATE")?;
            tx_open = true;
        }
        let mut update = conn
            .prepare_cached("UPDATE works SET work_name = ?1 WHERE id = ?2")?;
        for (val, id) in pending.drain(..) {
            update.execute(params![val, id])?;
            fixed_total += 1;
        }
    }
    if tx_open {
        conn.execute_batch("COMMIT")?;
    }

    pb.finish_and_clear();
    let elapsed = started.elapsed();
    log_line(
        &mut log,
        &format!(
            "DONE scanned={scanned} fixed={fixed_total} elapsed={:.1}s",
            elapsed.as_secs_f64()
        ),
    );
    log_line(&mut log, "=== fix_work_name_encoding END ===");
    Ok(())
}
