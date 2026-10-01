/// Create individuals_floruit table from data/all_humans/all_human_floruit.json.
///
/// Schema:
///   wikidata_id        TEXT PRIMARY KEY
///   floruit_date       TEXT       (raw Wikidata datetime, e.g. "+1450-01-01T00:00:00Z" or "-0050-...")
///   floruit_precision  INTEGER    (Wikidata timePrecision: 11 day .. 7 century .. 6 10x century)
///   floruit_year       INTEGER    (signed year extracted from floruit_date — may be negative for BCE)
///
/// Independent of individuals_impact_date — does NOT merge.
use anyhow::{Context, Result};
use rusqlite::{params, Connection};
use serde::Deserialize;
use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::time::Instant;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const FLORUIT_JSON: &str = "data/all_humans/all_human_floruit.json";
const TASK_LOG: &str = "task.log";

#[derive(Debug, Deserialize)]
struct FloruitEntry {
    floruit_date: Option<String>,
    floruit_precision: Option<i64>,
}

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

/// Parse year from a Wikidata datetime literal like
/// "+1450-01-01T00:00:00Z" or "-0050-01-01T00:00:00Z".
fn parse_year(date: &str) -> Option<i64> {
    let s = date.trim();
    if s.is_empty() || s.starts_with("_:") {
        return None;
    }
    let (negative, rest) = if let Some(r) = s.strip_prefix('-') {
        (true, r)
    } else if let Some(r) = s.strip_prefix('+') {
        (false, r)
    } else {
        (false, s)
    };
    let year_str = rest.split('-').next()?;
    let y: i64 = year_str.parse().ok()?;
    Some(if negative { -y } else { y })
}

fn main() -> Result<()> {
    let total_start = Instant::now();
    log("=== Step 59: Create individuals_floruit table ===");

    let raw = fs::read_to_string(FLORUIT_JSON)
        .with_context(|| format!("reading {}", FLORUIT_JSON))?;
    let map: HashMap<String, FloruitEntry> =
        serde_json::from_str(&raw).context("parsing floruit JSON")?;
    log(&format!("[59] Loaded {} floruit entries from JSON", map.len()));

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    conn.execute_batch("DROP TABLE IF EXISTS individuals_floruit;")?;
    conn.execute_batch(
        "CREATE TABLE individuals_floruit (
            wikidata_id       TEXT PRIMARY KEY,
            floruit_date      TEXT,
            floruit_precision INTEGER,
            floruit_year      INTEGER
        );",
    )?;
    log("[59] Created table individuals_floruit");

    let step = Instant::now();
    conn.execute_batch("BEGIN TRANSACTION;")?;

    let mut inserted: i64 = 0;
    let mut bad_year: i64 = 0;
    {
        let mut ins = conn.prepare(
            "INSERT INTO individuals_floruit (wikidata_id, floruit_date, floruit_precision, floruit_year)
             VALUES (?1, ?2, ?3, ?4)",
        )?;

        for (qid, entry) in &map {
            let year_opt = entry.floruit_date.as_deref().and_then(parse_year);
            if entry.floruit_date.is_some() && year_opt.is_none() {
                bad_year += 1;
            }
            ins.execute(params![
                qid,
                entry.floruit_date,
                entry.floruit_precision,
                year_opt,
            ])?;
            inserted += 1;
            if inserted % 25_000 == 0 {
                log(&format!(
                    "[59]   Inserted {}/{} ({})",
                    inserted,
                    map.len(),
                    elapsed(step)
                ));
            }
        }
    }
    conn.execute_batch("COMMIT;")?;
    log(&format!(
        "[59] Insert complete: {} rows in {}",
        inserted,
        elapsed(step)
    ));

    let idx = Instant::now();
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_floruit_year ON individuals_floruit(floruit_year);
         CREATE INDEX IF NOT EXISTS idx_floruit_precision ON individuals_floruit(floruit_precision);",
    )?;
    log(&format!("[59] Indexes created ({})", elapsed(idx)));

    let total_rows: i64 =
        conn.query_row("SELECT COUNT(*) FROM individuals_floruit", [], |r| r.get(0))?;
    let with_year: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals_floruit WHERE floruit_year IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    let with_prec: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals_floruit WHERE floruit_precision IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    let min_year: Option<i64> = conn
        .query_row(
            "SELECT MIN(floruit_year) FROM individuals_floruit",
            [],
            |r| r.get(0),
        )
        .ok();
    let max_year: Option<i64> = conn
        .query_row(
            "SELECT MAX(floruit_year) FROM individuals_floruit",
            [],
            |r| r.get(0),
        )
        .ok();

    log("[59] === Summary ===");
    log(&format!("[59]   Rows: {}", total_rows));
    log(&format!("[59]   With year:      {}", with_year));
    log(&format!("[59]   With precision: {}", with_prec));
    log(&format!("[59]   Year range:     {:?} .. {:?}", min_year, max_year));
    log(&format!("[59]   Bad/parsefail:  {}", bad_year));

    log("[59] Sample rows:");
    let mut s = conn.prepare(
        "SELECT wikidata_id, floruit_date, floruit_precision, floruit_year
         FROM individuals_floruit ORDER BY floruit_year LIMIT 5",
    )?;
    let rows: Vec<(String, Option<String>, Option<i64>, Option<i64>)> = s
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)))?
        .filter_map(|r| r.ok())
        .collect();
    for (q, d, p, y) in rows {
        log(&format!(
            "[59]   {} | {:?} | prec={:?} | year={:?}",
            q, d, p, y
        ));
    }

    log(&format!(
        "=== Step 59 complete (total: {}) ===",
        elapsed(total_start)
    ));
    Ok(())
}
