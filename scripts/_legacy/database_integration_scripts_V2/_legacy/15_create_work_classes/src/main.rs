// Build the `work_classes` table in humans_clean.sqlite3 from the JSON
// files produced by scripts/wikidata_extraction_scripts_v2/15_extract_work_instance_of.py.
//
// Schema:
//   work_classes(
//       work_id        TEXT PRIMARY KEY,   -- Q-id of the work
//       main_class_id  TEXT NOT NULL,      -- main P31 (truthy) class
//       main_class_en  TEXT,               -- English label of main_class_id
//       n_classes      INTEGER NOT NULL    -- total P31 values for the work
//   )
//   INDEX idx_work_classes_main ON work_classes(main_class_id)
//
// Drops + recreates the table so the script is idempotent.

use anyhow::{Context, Result};
use chrono::Local;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection, OpenFlags};
use serde_json::Value;
use std::collections::BTreeMap;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::time::Instant;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const OUT_BASE: &str = "data/all_humans/wikidata_extraction_scripts_v2";
const LOG_PATH: &str = "logs/15_create_work_classes.log";
const BATCH: usize = 50_000;

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

    log_line(&mut log, "=== 15_create_work_classes START ===");

    let main_path = format!("{OUT_BASE}/work_instance_of.json");
    let all_path = format!("{OUT_BASE}/work_instance_of_all.json");
    let lab_path = format!("{OUT_BASE}/work_instance_labels.json");

    log_line(&mut log, &format!("loading {main_path}"));
    let main_v = read_json(&main_path)?;
    log_line(&mut log, &format!("loading {all_path}"));
    let all_v = read_json(&all_path)?;
    log_line(&mut log, &format!("loading {lab_path}"));
    let lab_v = read_json(&lab_path)?;

    let main = main_v.as_object().context("main JSON not an object")?;
    let all = all_v.as_object().context("all JSON not an object")?;
    let labels = lab_v.as_object().context("labels JSON not an object")?;

    log_line(
        &mut log,
        &format!(
            "loaded: {} works (main), {} works (all), {} class labels",
            main.len(),
            all.len(),
            labels.len()
        ),
    );

    let conn = Connection::open_with_flags(
        DB_PATH,
        OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .with_context(|| format!("opening {DB_PATH}"))?;

    conn.pragma_update(None, "journal_mode", "WAL")?;
    conn.pragma_update(None, "synchronous", "NORMAL")?;
    conn.pragma_update(None, "temp_store", "MEMORY")?;
    conn.pragma_update(None, "cache_size", -1_000_000)?;

    log_line(&mut log, "DROP/CREATE work_classes table");
    conn.execute_batch(
        "DROP TABLE IF EXISTS work_classes;
         CREATE TABLE work_classes (
             work_id        TEXT PRIMARY KEY,
             main_class_id  TEXT NOT NULL,
             main_class_en  TEXT,
             n_classes      INTEGER NOT NULL
         );",
    )?;

    let pb = ProgressBar::new(main.len() as u64);
    pb.set_style(
        ProgressStyle::with_template("{spinner} {pos}/{len} ({percent}%) ETA {eta}").unwrap(),
    );

    // Sort keys for stable insertion order (helps PK b-tree builds slightly).
    // BTreeMap iterates sorted; we collect refs to avoid copies.
    let sorted: BTreeMap<&String, &Value> = main.iter().collect();

    let started = Instant::now();
    let mut inserted: u64 = 0;
    let mut milestone: u64 = 0;
    let mut buf: Vec<(String, String, Option<String>, i64)> = Vec::with_capacity(BATCH);

    let flush = |conn: &Connection,
                 buf: &mut Vec<(String, String, Option<String>, i64)>,
                 inserted: &mut u64|
     -> Result<()> {
        if buf.is_empty() {
            return Ok(());
        }
        let tx = conn.unchecked_transaction()?;
        {
            let mut stmt = tx.prepare_cached(
                "INSERT INTO work_classes
                   (work_id, main_class_id, main_class_en, n_classes)
                 VALUES (?1, ?2, ?3, ?4)",
            )?;
            for (w, c, lbl, n) in buf.drain(..) {
                stmt.execute(params![w, c, lbl, n])?;
                *inserted += 1;
            }
        }
        tx.commit()?;
        Ok(())
    };

    for (work_id, cls_v) in sorted {
        let main_class = match cls_v.as_str() {
            Some(s) => s.to_string(),
            None => continue,
        };
        // n_classes from `all` map; default 1 if missing
        let n_classes: i64 = match all.get(work_id) {
            Some(Value::Array(a)) => a.len() as i64,
            _ => 1,
        };
        let label = labels
            .get(&main_class)
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());

        buf.push((work_id.clone(), main_class, label, n_classes));
        if buf.len() >= BATCH {
            flush(&conn, &mut buf, &mut inserted)?;
            pb.set_position(inserted);
            if inserted - milestone >= 1_000_000 {
                milestone = inserted;
                log_line(
                    &mut log,
                    &format!("inserted={inserted}  elapsed={:.1}s", started.elapsed().as_secs_f64()),
                );
            }
        }
    }
    flush(&conn, &mut buf, &mut inserted)?;
    pb.set_position(inserted);
    pb.finish_and_clear();

    log_line(
        &mut log,
        &format!("CREATE INDEX idx_work_classes_main on main_class_id"),
    );
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_work_classes_main
         ON work_classes(main_class_id);",
    )?;

    let row_count: i64 = conn.query_row("SELECT COUNT(*) FROM work_classes", [], |r| r.get(0))?;
    let labelled: i64 = conn.query_row(
        "SELECT COUNT(*) FROM work_classes WHERE main_class_en IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    let multi: i64 = conn.query_row(
        "SELECT COUNT(*) FROM work_classes WHERE n_classes > 1",
        [],
        |r| r.get(0),
    )?;

    log_line(
        &mut log,
        &format!(
            "DONE rows={row_count} labelled={labelled} multi_class={multi} elapsed={:.1}s",
            started.elapsed().as_secs_f64()
        ),
    );
    log_line(&mut log, "=== 15_create_work_classes END ===");

    Ok(())
}
