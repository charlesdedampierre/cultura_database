// Add `instance_of` and `instance_of_en` columns to the `works` table and
// populate them from work_instance_of_all.json + work_instance_labels.json
// produced by scripts/wikidata_extraction_scripts_v2/15_extract_work_instance_of.py.
//
// When a work has multiple P31 values, they are joined with '|' (sorted to
// give stable output). Likewise for the English labels — index-aligned so
// instance_of[i] corresponds to instance_of_en[i].
//
// Drops the standalone `work_classes` table created by the previous step
// (now superseded by these inline columns).
//
// All 38M rows of `works` get touched, but the per-work map is only 17M
// distinct keys; we look up via WHERE work_id = ? (uses idx_works_work).

use anyhow::{Context, Result};
use chrono::Local;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection, OpenFlags};
use serde_json::Value;
use std::collections::HashMap;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::time::Instant;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const OUT_BASE: &str = "data/all_humans/wikidata_extraction_scripts_v2";
const LOG_PATH: &str = "logs/16_add_instance_to_works.log";
const BATCH: usize = 20_000;

fn log_line(log: &mut std::fs::File, msg: &str) {
    let stamped = format!("[{}] {}", Local::now().format("%Y-%m-%d %H:%M:%S"), msg);
    println!("{stamped}");
    let _ = writeln!(log, "{stamped}");
    let _ = log.flush();
}

fn read_json(path: &str) -> Result<Value> {
    let f = std::fs::File::open(path).with_context(|| format!("opening {path}"))?;
    let v: Value = serde_json::from_reader(std::io::BufReader::new(f))
        .with_context(|| format!("parsing {path}"))?;
    Ok(v)
}

/// Add a column if it doesn't already exist (ALTER TABLE ADD COLUMN is
/// fast on SQLite, but errors if the column is already there).
fn add_column_if_missing(conn: &Connection, col: &str) -> Result<()> {
    let exists: bool = conn
        .prepare("SELECT 1 FROM pragma_table_info('works') WHERE name = ?1")?
        .query_map([col], |_| Ok(()))?
        .next()
        .is_some();
    if !exists {
        conn.execute_batch(&format!("ALTER TABLE works ADD COLUMN {col} TEXT;"))?;
    }
    Ok(())
}

fn main() -> Result<()> {
    if !Path::new(DB_PATH).exists() {
        anyhow::bail!("DB not found at {DB_PATH}. Run from project root.");
    }
    std::fs::create_dir_all("logs").ok();
    let mut log = OpenOptions::new()
        .create(true)
        .append(true)
        .open(LOG_PATH)
        .with_context(|| format!("opening log {LOG_PATH}"))?;

    log_line(&mut log, "=== 16_add_instance_to_works START ===");

    let all_path = format!("{OUT_BASE}/work_instance_of_all.json");
    let lab_path = format!("{OUT_BASE}/work_instance_labels.json");

    log_line(&mut log, &format!("loading {all_path}"));
    let all_v = read_json(&all_path)?;
    log_line(&mut log, &format!("loading {lab_path}"));
    let lab_v = read_json(&lab_path)?;

    let all = all_v.as_object().context("all JSON not an object")?;
    let labels = lab_v.as_object().context("labels JSON not an object")?;
    log_line(
        &mut log,
        &format!("loaded: {} works, {} class labels", all.len(), labels.len()),
    );

    // Build per-work pipe-joined strings (sorted for stable output).
    log_line(&mut log, "building per-work join strings");
    let mut prepared: Vec<(String, String, Option<String>)> = Vec::with_capacity(all.len());
    for (work_id, cls_v) in all {
        let arr = match cls_v.as_array() {
            Some(a) => a,
            None => continue,
        };
        let mut classes: Vec<&str> = arr.iter().filter_map(|v| v.as_str()).collect();
        if classes.is_empty() {
            continue;
        }
        classes.sort_unstable();
        let class_str = classes.join("|");
        // Aligned labels — empty string when missing so positions stay matched.
        // Skip building label_str entirely if no labels at all (rare).
        let any_labelled = classes
            .iter()
            .any(|c| labels.get(*c).and_then(|v| v.as_str()).is_some());
        let label_str = if any_labelled {
            Some(
                classes
                    .iter()
                    .map(|c| labels.get(*c).and_then(|v| v.as_str()).unwrap_or(""))
                    .collect::<Vec<_>>()
                    .join("|"),
            )
        } else {
            None
        };
        prepared.push((work_id.clone(), class_str, label_str));
    }
    log_line(&mut log, &format!("prepared {} (work_id → str) entries", prepared.len()));

    let conn = Connection::open_with_flags(
        DB_PATH,
        OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .with_context(|| format!("opening {DB_PATH}"))?;

    conn.pragma_update(None, "journal_mode", "WAL")?;
    conn.pragma_update(None, "synchronous", "NORMAL")?;
    conn.pragma_update(None, "temp_store", "MEMORY")?;
    conn.pragma_update(None, "cache_size", -1_000_000)?;

    // Drop the previously-created work_classes table.
    log_line(&mut log, "DROP TABLE IF EXISTS work_classes (superseded by columns on works)");
    conn.execute_batch("DROP TABLE IF EXISTS work_classes;")?;

    log_line(&mut log, "ALTER TABLE works ADD COLUMN instance_of TEXT (if missing)");
    add_column_if_missing(&conn, "instance_of")?;
    log_line(&mut log, "ALTER TABLE works ADD COLUMN instance_of_en TEXT (if missing)");
    add_column_if_missing(&conn, "instance_of_en")?;

    // Use a temp table keyed by work_id, then a single UPDATE join. This is
    // dramatically faster than 17M individual UPDATE WHERE work_id = ?
    // statements (each of which does a separate b-tree lookup on
    // idx_works_work and then writes ~2.3 rows).
    log_line(&mut log, "CREATE TEMP TABLE wi(work_id PK, instance_of, instance_of_en)");
    conn.execute_batch(
        "CREATE TEMP TABLE wi (
             work_id        TEXT PRIMARY KEY,
             instance_of    TEXT NOT NULL,
             instance_of_en TEXT
         );",
    )?;

    let pb = ProgressBar::new(prepared.len() as u64);
    pb.set_style(
        ProgressStyle::with_template("temp insert: {pos}/{len} ({percent}%) ETA {eta}").unwrap(),
    );

    let started = Instant::now();
    let mut inserted: u64 = 0;
    let mut milestone: u64 = 0;
    let mut iter = prepared.iter();
    loop {
        let mut batch_n = 0;
        let tx = conn.unchecked_transaction()?;
        {
            let mut stmt = tx.prepare_cached(
                "INSERT INTO temp.wi (work_id, instance_of, instance_of_en)
                 VALUES (?1, ?2, ?3)",
            )?;
            for (w, c, l) in (&mut iter).take(BATCH) {
                stmt.execute(params![w, c, l.as_deref()])?;
                batch_n += 1;
            }
        }
        tx.commit()?;
        if batch_n == 0 {
            break;
        }
        inserted += batch_n as u64;
        pb.set_position(inserted);
        if inserted - milestone >= 1_000_000 {
            milestone = inserted;
            log_line(
                &mut log,
                &format!("temp inserted={inserted}  elapsed={:.1}s",
                         started.elapsed().as_secs_f64()),
            );
        }
    }
    pb.finish_and_clear();
    log_line(&mut log, &format!("temp.wi populated ({} rows)", inserted));

    log_line(&mut log, "UPDATE works SET instance_of/_en FROM temp.wi (single statement)");
    let upd_started = Instant::now();
    let touched = conn.execute(
        "UPDATE works
         SET instance_of    = (SELECT instance_of    FROM temp.wi WHERE temp.wi.work_id = works.work_id),
             instance_of_en = (SELECT instance_of_en FROM temp.wi WHERE temp.wi.work_id = works.work_id)
         WHERE works.work_id IN (SELECT work_id FROM temp.wi);",
        [],
    )?;
    log_line(
        &mut log,
        &format!("UPDATE touched {touched} rows in {:.1}s",
                 upd_started.elapsed().as_secs_f64()),
    );

    let total_rows: i64 = conn.query_row("SELECT COUNT(*) FROM works", [], |r| r.get(0))?;
    let with_inst: i64 = conn.query_row(
        "SELECT COUNT(*) FROM works WHERE instance_of IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    let multi: i64 = conn.query_row(
        "SELECT COUNT(*) FROM works WHERE instance_of LIKE '%|%'",
        [],
        |r| r.get(0),
    )?;

    log_line(
        &mut log,
        &format!(
            "DONE works={total_rows} with_instance={with_inst} pipe_separated={multi} total_elapsed={:.1}s",
            started.elapsed().as_secs_f64()
        ),
    );
    log_line(&mut log, "=== 16_add_instance_to_works END ===");
    Ok(())
}
