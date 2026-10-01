/// 58: Add `is_urban_settlement` column to `cities` based on the urban/not-urban
/// classification of Wikidata P31 classes produced by
/// `extraction_scripts/all_humans/36_classify_entity_types_urban.py`.
///
/// Rule: a city is an urban settlement (is_urban_settlement=1) if ANY of its
/// P31 ids is classified urban_settlement=true. Otherwise 0. NULL if the city
/// has no P31 data at all (should be rare).
use anyhow::{Context, Result};
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection};
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::fs;
use std::io::Write;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const CLASSIFICATION_PATH: &str = "data/all_humans/entity_type_classification.json";
const TASK_LOG: &str = "task.log";

fn log(msg: &str) {
    println!("{}", msg);
    let mut f = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(TASK_LOG)
        .unwrap();
    writeln!(f, "{}", msg).unwrap();
}

fn column_exists(conn: &Connection, table: &str, col: &str) -> Result<bool> {
    let mut stmt = conn.prepare(&format!("PRAGMA table_info({})", table))?;
    let names: Vec<String> = stmt
        .query_map([], |row| row.get::<_, String>(1))?
        .filter_map(|r| r.ok())
        .collect();
    Ok(names.iter().any(|n| n == col))
}

fn main() -> Result<()> {
    log("=== Step 58: Add is_urban_settlement to cities ===");

    let json = fs::read_to_string(CLASSIFICATION_PATH)
        .with_context(|| format!("reading {}", CLASSIFICATION_PATH))?;
    let raw: HashMap<String, Value> = serde_json::from_str(&json)?;
    log(&format!("[58] Loaded classification for {} P31 ids", raw.len()));

    // Build a set of P31 ids classified as urban.
    let urban_ids: HashSet<String> = raw
        .iter()
        .filter_map(|(k, v)| {
            if v.get("urban_settlement")
                .and_then(|x| x.as_bool())
                .unwrap_or(false)
            {
                Some(k.clone())
            } else {
                None
            }
        })
        .collect();
    log(&format!("[58] Urban P31 ids: {}", urban_ids.len()));

    let mut conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    if column_exists(&conn, "cities", "is_urban_settlement")? {
        log("[58] cities.is_urban_settlement already exists — clearing values");
        conn.execute("UPDATE cities SET is_urban_settlement = NULL", [])?;
    } else {
        conn.execute_batch("ALTER TABLE cities ADD COLUMN is_urban_settlement INTEGER;")?;
        log("[58] Added column cities.is_urban_settlement");
    }

    // Read all (id, entity_type_ids) rows. The entity_type_ids column is
    // pipe-separated P31 Q-ids (from step 57).
    let mut rows: Vec<(String, Option<String>)> = Vec::new();
    {
        let mut stmt = conn.prepare("SELECT id, entity_type_ids FROM cities")?;
        let it = stmt.query_map([], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, Option<String>>(1)?))
        })?;
        for r in it {
            rows.push(r?);
        }
    }
    log(&format!("[58] Read {} cities", rows.len()));

    let tx = conn.transaction()?;
    let mut updated = 0usize;
    let mut urban_count = 0usize;
    let mut non_urban_count = 0usize;
    let mut null_count = 0usize;
    {
        let mut stmt =
            tx.prepare("UPDATE cities SET is_urban_settlement = ?1 WHERE id = ?2")?;
        let pb = ProgressBar::new(rows.len() as u64);
        pb.set_style(
            ProgressStyle::with_template(
                "  {msg} [{bar:40.cyan/blue}] {pos}/{len} ({percent}%) eta {eta}",
            )
            .unwrap()
            .progress_chars("=>-"),
        );
        pb.set_message("Updating cities");

        for (qid, etypes) in &rows {
            let val: Option<i64> = match etypes {
                None => None,
                Some(s) if s.is_empty() => None,
                Some(s) => {
                    let is_urban =
                        s.split('|').any(|tid| urban_ids.contains(tid));
                    Some(if is_urban { 1 } else { 0 })
                }
            };
            match val {
                Some(1) => urban_count += 1,
                Some(0) => non_urban_count += 1,
                _ => null_count += 1,
            }
            let u = stmt.execute(params![val, qid])?;
            updated += u as usize;
            pb.inc(1);
        }
        pb.finish_with_message("Updating cities done");
    }
    tx.commit()?;

    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_cities_is_urban_settlement ON cities(is_urban_settlement);",
    )?;

    log(&format!("[58] rows updated: {}", updated));
    log(&format!(
        "[58]   is_urban_settlement=1 : {} ({:.1}%)",
        urban_count,
        100.0 * urban_count as f64 / rows.len().max(1) as f64
    ));
    log(&format!(
        "[58]   is_urban_settlement=0 : {} ({:.1}%)",
        non_urban_count,
        100.0 * non_urban_count as f64 / rows.len().max(1) as f64
    ));
    log(&format!(
        "[58]   NULL                   : {} ({:.1}%)",
        null_count,
        100.0 * null_count as f64 / rows.len().max(1) as f64
    ));

    // Spot check
    let mut stmt = conn.prepare(
        "SELECT id, name_en, is_urban_settlement, entity_type FROM cities
         WHERE id IN ('Q100','Q30','Q771','Q60','Q90','Q1537')",
    )?;
    let spot: Vec<(String, Option<String>, Option<i64>, Option<String>)> = stmt
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[58] Spot check:");
    for (id, name, u, et) in spot {
        log(&format!(
            "[58]   {} {:<20} urban={} types={}",
            id,
            name.as_deref().unwrap_or("?"),
            match u {
                Some(1) => "YES",
                Some(0) => "no ",
                _ => "NULL",
            },
            et.as_deref().unwrap_or("-")
        ));
    }

    log("=== Step 58 complete ===");
    Ok(())
}
