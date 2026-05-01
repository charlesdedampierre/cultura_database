/// Create works table from data/all_humans/all_human_works.tsv + work_labels.json.
///
/// Schema:
///   id              INTEGER PRIMARY KEY AUTOINCREMENT
///   individual_id   TEXT       (Wikidata QID of the human)
///   individual_name TEXT       (joined from individuals.name_en)
///   work_id         TEXT       (Wikidata QID of the work)
///   work_name       TEXT       (English label, joined from work_labels.json)
///   relationship    TEXT       (Wikidata property: P50, P170, P86, P57, P162, P98, P175, P110, P58)
///
/// One row per (individual, work, relationship) — a work counted under multiple
/// roles will appear multiple times (e.g. director + screenwriter).
use anyhow::{Context, Result};
use rusqlite::{params, Connection};
use std::collections::HashMap;
use std::fs::{self, File};
use std::io::{BufRead, BufReader, Write};
use std::time::Instant;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const WORKS_TSV: &str = "data/all_humans/all_human_works.tsv";
const LABELS_JSON: &str = "data/all_humans/work_labels.json";
const TASK_LOG: &str = "task.log";

fn now_clock() -> String {
    let dur = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap();
    let secs = dur.as_secs();
    let h = (secs % 86400) / 3600;
    let m = (secs % 3600) / 60;
    let s = secs % 60;
    format!("{:02}:{:02}:{:02} UTC", h, m, s)
}

fn log(msg: &str) {
    let line = format!("[{}] {}", now_clock(), msg);
    println!("{}", line);
    let mut f = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(TASK_LOG)
        .unwrap();
    writeln!(f, "{}", line).unwrap();
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
    log("=== Step 62: Create works table ===");

    // Load work labels
    let raw = fs::read_to_string(LABELS_JSON)
        .with_context(|| format!("reading {}", LABELS_JSON))?;
    let work_labels: HashMap<String, String> =
        serde_json::from_str(&raw).context("parsing work labels JSON")?;
    log(&format!("[62] Loaded {} work labels", work_labels.len()));

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // Load individual names (wikidata_id -> name_en)
    let mut indiv_names: HashMap<String, String> = HashMap::new();
    {
        let mut s = conn.prepare("SELECT wikidata_id, name_en FROM individuals")?;
        let rows = s.query_map([], |r| {
            let id: String = r.get(0)?;
            let name: Option<String> = r.get(1)?;
            Ok((id, name))
        })?;
        for row in rows {
            let (id, name) = row?;
            if let Some(n) = name {
                indiv_names.insert(id, n);
            }
        }
    }
    log(&format!("[62] Loaded {} individual names", indiv_names.len()));

    conn.execute_batch("DROP TABLE IF EXISTS works;")?;
    conn.execute_batch(
        "CREATE TABLE works (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            individual_id   TEXT NOT NULL,
            individual_name TEXT,
            work_id         TEXT NOT NULL,
            work_name       TEXT,
            relationship    TEXT NOT NULL
        );",
    )?;
    log("[62] Created table works");

    let step = Instant::now();
    conn.execute_batch("BEGIN TRANSACTION;")?;

    let mut inserted: i64 = 0;
    let mut skipped_header = false;
    let mut missing_indiv: i64 = 0;
    let mut missing_label: i64 = 0;

    {
        let mut ins = conn.prepare(
            "INSERT INTO works (individual_id, individual_name, work_id, work_name, relationship)
             VALUES (?1, ?2, ?3, ?4, ?5)",
        )?;

        let f = File::open(WORKS_TSV).with_context(|| format!("opening {}", WORKS_TSV))?;
        let reader = BufReader::new(f);

        for line in reader.lines() {
            let line = line?;
            if !skipped_header {
                skipped_header = true;
                continue;
            }
            let parts: Vec<&str> = line.split('\t').collect();
            if parts.len() < 3 {
                continue;
            }
            let individual_id = parts[0];
            let work_id = parts[1];
            let relationship = parts[2];

            let individual_name = indiv_names.get(individual_id);
            if individual_name.is_none() {
                missing_indiv += 1;
            }
            let work_name = work_labels.get(work_id);
            if work_name.is_none() {
                missing_label += 1;
            }

            ins.execute(params![
                individual_id,
                individual_name,
                work_id,
                work_name,
                relationship,
            ])?;
            inserted += 1;

            if inserted % 250_000 == 0 {
                log(&format!(
                    "[62]   Inserted {} rows ({})",
                    inserted,
                    elapsed(step)
                ));
            }
        }
    }

    conn.execute_batch("COMMIT;")?;
    log(&format!(
        "[62] Insert complete: {} rows in {}",
        inserted,
        elapsed(step)
    ));

    let idx = Instant::now();
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_works_individual ON works(individual_id);
         CREATE INDEX IF NOT EXISTS idx_works_work       ON works(work_id);
         CREATE INDEX IF NOT EXISTS idx_works_rel        ON works(relationship);",
    )?;
    log(&format!("[62] Indexes created ({})", elapsed(idx)));

    let total_rows: i64 = conn.query_row("SELECT COUNT(*) FROM works", [], |r| r.get(0))?;
    let unique_humans: i64 = conn.query_row(
        "SELECT COUNT(DISTINCT individual_id) FROM works",
        [],
        |r| r.get(0),
    )?;
    let unique_works: i64 = conn.query_row(
        "SELECT COUNT(DISTINCT work_id) FROM works",
        [],
        |r| r.get(0),
    )?;

    log("[62] === Summary ===");
    log(&format!("[62]   Rows:                 {}", total_rows));
    log(&format!("[62]   Distinct individuals: {}", unique_humans));
    log(&format!("[62]   Distinct works:       {}", unique_works));
    log(&format!("[62]   Missing indiv name:   {}", missing_indiv));
    log(&format!("[62]   Missing work label:   {}", missing_label));

    log("[62] Per-relationship counts:");
    let mut s = conn.prepare(
        "SELECT relationship, COUNT(*) FROM works GROUP BY relationship ORDER BY 2 DESC",
    )?;
    let rows: Vec<(String, i64)> = s
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
        .filter_map(|r| r.ok())
        .collect();
    for (rel, n) in rows {
        log(&format!("[62]   {:<5} {:>12}", rel, n));
    }

    log("[62] Sample rows:");
    let mut s = conn.prepare(
        "SELECT individual_id, individual_name, work_id, work_name, relationship
         FROM works LIMIT 5",
    )?;
    let rows: Vec<(String, Option<String>, String, Option<String>, String)> = s
        .query_map([], |r| {
            Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?))
        })?
        .filter_map(|r| r.ok())
        .collect();
    for (iid, iname, wid, wname, rel) in rows {
        log(&format!(
            "[62]   {} ({:?}) -> {} ({:?}) [{}]",
            iid, iname, wid, wname, rel
        ));
    }

    log(&format!(
        "=== Step 62 complete (total: {}) ===",
        elapsed(total_start)
    ));
    Ok(())
}
