// Add inception/publication date columns to the `works` table and populate
// them from work_inception.json + work_publication.json produced by
// scripts/wikidata_extraction_scripts_v2/19_extract_work_dates.py.
//
// New columns on works (TEXT/INTEGER, NULL when missing):
//   inception_date            ISO timestamp (e.g. "1786-04-06T00:00:00Z")
//   inception_precision       11=day .. 7=century (Wikidata convention)
//   publication_date          ISO timestamp
//   publication_precision     same convention
//
// Strategy mirrors 16_add_instance_to_works/: build a temp table keyed by
// work_id, then a single UPDATE … FROM temp.wd (one b-tree pass on the
// works table instead of 17M individual UPDATEs).

use anyhow::{Context, Result};
use chrono::Local;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection, OpenFlags};
use serde_json::Value;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::time::Instant;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const OUT_BASE: &str = "data/all_humans/wikidata_extraction_scripts_v2";
const LOG_PATH: &str = "logs/19_add_dates_to_works.log";
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

fn add_column_if_missing(conn: &Connection, col: &str, ty: &str) -> Result<()> {
    let exists: bool = conn
        .prepare("SELECT 1 FROM pragma_table_info('works') WHERE name = ?1")?
        .query_map([col], |_| Ok(()))?
        .next()
        .is_some();
    if !exists {
        conn.execute_batch(&format!("ALTER TABLE works ADD COLUMN {col} {ty};"))?;
    }
    Ok(())
}

/// Per-work date entry built from one of the per-prop JSONs.
#[derive(Default, Clone)]
struct DateEntry {
    inc_date: Option<String>,
    inc_prec: Option<i64>,
    pub_date: Option<String>,
    pub_prec: Option<i64>,
}

fn ingest(json: &Value, set_inc: bool, into: &mut std::collections::HashMap<String, DateEntry>) -> Result<usize> {
    let obj = json.as_object().context("expected JSON object")?;
    let mut n = 0usize;
    for (work_id, v) in obj {
        let m = match v.as_object() {
            Some(m) => m,
            None => continue,
        };
        let date = m.get("date").and_then(|x| x.as_str()).map(|s| s.to_string());
        let prec = m.get("precision").and_then(|x| x.as_i64());
        if date.is_none() && prec.is_none() {
            continue;
        }
        let entry = into.entry(work_id.clone()).or_default();
        if set_inc {
            entry.inc_date = date;
            entry.inc_prec = prec;
        } else {
            entry.pub_date = date;
            entry.pub_prec = prec;
        }
        n += 1;
    }
    Ok(n)
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

    log_line(&mut log, "=== 19_add_dates_to_works START ===");

    let inc_path = format!("{OUT_BASE}/work_inception.json");
    let pub_path = format!("{OUT_BASE}/work_publication.json");

    log_line(&mut log, &format!("loading {inc_path}"));
    let inc_v = read_json(&inc_path)?;
    log_line(&mut log, &format!("loading {pub_path}"));
    let pub_v = read_json(&pub_path)?;

    let mut by_work: std::collections::HashMap<String, DateEntry> =
        std::collections::HashMap::with_capacity(16_000_000);
    let n_inc = ingest(&inc_v, true, &mut by_work)?;
    let n_pub = ingest(&pub_v, false, &mut by_work)?;
    drop(inc_v);
    drop(pub_v);
    log_line(
        &mut log,
        &format!("ingested: {n_inc} inception entries, {n_pub} publication entries → {} unique works",
                 by_work.len()),
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

    log_line(&mut log, "ALTER TABLE works ADD COLUMN inception_date TEXT (if missing)");
    add_column_if_missing(&conn, "inception_date", "TEXT")?;
    log_line(&mut log, "ALTER TABLE works ADD COLUMN inception_precision INTEGER (if missing)");
    add_column_if_missing(&conn, "inception_precision", "INTEGER")?;
    log_line(&mut log, "ALTER TABLE works ADD COLUMN publication_date TEXT (if missing)");
    add_column_if_missing(&conn, "publication_date", "TEXT")?;
    log_line(&mut log, "ALTER TABLE works ADD COLUMN publication_precision INTEGER (if missing)");
    add_column_if_missing(&conn, "publication_precision", "INTEGER")?;

    log_line(&mut log, "CREATE TEMP TABLE wd(work_id PK, inc_date, inc_prec, pub_date, pub_prec)");
    conn.execute_batch(
        "CREATE TEMP TABLE wd (
             work_id  TEXT PRIMARY KEY,
             inc_date TEXT,
             inc_prec INTEGER,
             pub_date TEXT,
             pub_prec INTEGER
         );",
    )?;

    let pb = ProgressBar::new(by_work.len() as u64);
    pb.set_style(
        ProgressStyle::with_template("temp insert: {pos}/{len} ({percent}%) ETA {eta}").unwrap(),
    );

    let started = Instant::now();
    let mut inserted: u64 = 0;
    let mut milestone: u64 = 0;
    let mut iter = by_work.iter();
    loop {
        let mut batch_n = 0;
        let tx = conn.unchecked_transaction()?;
        {
            let mut stmt = tx.prepare_cached(
                "INSERT INTO temp.wd (work_id, inc_date, inc_prec, pub_date, pub_prec)
                 VALUES (?1, ?2, ?3, ?4, ?5)",
            )?;
            for (w, e) in (&mut iter).take(BATCH) {
                stmt.execute(params![
                    w,
                    e.inc_date.as_deref(),
                    e.inc_prec,
                    e.pub_date.as_deref(),
                    e.pub_prec,
                ])?;
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
    log_line(&mut log, &format!("temp.wd populated ({} rows)", inserted));

    log_line(&mut log, "UPDATE works SET inception_*/publication_* FROM temp.wd");
    let upd_started = Instant::now();
    let touched = conn.execute(
        "UPDATE works
         SET inception_date        = (SELECT inc_date FROM temp.wd WHERE temp.wd.work_id = works.work_id),
             inception_precision   = (SELECT inc_prec FROM temp.wd WHERE temp.wd.work_id = works.work_id),
             publication_date      = (SELECT pub_date FROM temp.wd WHERE temp.wd.work_id = works.work_id),
             publication_precision = (SELECT pub_prec FROM temp.wd WHERE temp.wd.work_id = works.work_id)
         WHERE works.work_id IN (SELECT work_id FROM temp.wd);",
        [],
    )?;
    log_line(
        &mut log,
        &format!("UPDATE touched {touched} rows in {:.1}s",
                 upd_started.elapsed().as_secs_f64()),
    );

    let total_rows: i64 = conn.query_row("SELECT COUNT(*) FROM works", [], |r| r.get(0))?;
    let with_inc: i64 = conn.query_row(
        "SELECT COUNT(*) FROM works WHERE inception_date IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    let with_pub: i64 = conn.query_row(
        "SELECT COUNT(*) FROM works WHERE publication_date IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    let with_either: i64 = conn.query_row(
        "SELECT COUNT(*) FROM works WHERE inception_date IS NOT NULL OR publication_date IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    let distinct_inc: i64 = conn.query_row(
        "SELECT COUNT(DISTINCT work_id) FROM works WHERE inception_date IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    let distinct_pub: i64 = conn.query_row(
        "SELECT COUNT(DISTINCT work_id) FROM works WHERE publication_date IS NOT NULL",
        [],
        |r| r.get(0),
    )?;

    log_line(
        &mut log,
        &format!(
            "DONE works_rows={total_rows} \
             rows_with_inception={with_inc} rows_with_publication={with_pub} rows_with_either={with_either} \
             distinct_works_inception={distinct_inc} distinct_works_publication={distinct_pub} \
             total_elapsed={:.1}s",
            started.elapsed().as_secs_f64()
        ),
    );
    log_line(&mut log, "=== 19_add_dates_to_works END ===");
    Ok(())
}
