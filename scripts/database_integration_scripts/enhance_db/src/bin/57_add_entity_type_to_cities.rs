/// 57: Add `entity_type` and `entity_type_ids` columns to the cities table from
/// the Wikidata P31 (instance of) values previously fetched by
/// `extraction_scripts/all_humans/35_fetch_city_entity_types.py`.
///
/// Input : data/all_humans/city_entity_types.json
/// Output: cities.entity_type     (pipe-separated English labels,   e.g. "city|big city")
///         cities.entity_type_ids (pipe-separated Wikidata Q-ids,   e.g. "Q515|Q1549591")
use anyhow::{Context, Result};
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection};
use serde_json::Value;
use std::collections::HashMap;
use std::fs;
use std::io::Write;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const TYPES_PATH: &str = "data/all_humans/city_entity_types.json";
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
    log("=== Step 57: Add entity_type to cities ===");

    let types_json =
        fs::read_to_string(TYPES_PATH).with_context(|| format!("reading {}", TYPES_PATH))?;
    let types_map: HashMap<String, Value> =
        serde_json::from_str(&types_json).context("parsing city_entity_types.json")?;
    log(&format!(
        "[57] Loaded {} cities with P31 data",
        types_map.len()
    ));

    let mut conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    for (col, typ) in [("entity_type", "TEXT"), ("entity_type_ids", "TEXT")] {
        if column_exists(&conn, "cities", col)? {
            log(&format!("[57] cities.{} already exists — clearing values", col));
            conn.execute(&format!("UPDATE cities SET {} = NULL", col), [])?;
        } else {
            conn.execute_batch(&format!("ALTER TABLE cities ADD COLUMN {} {};", col, typ))?;
            log(&format!("[57] Added column cities.{}", col));
        }
    }

    let tx = conn.transaction()?;
    let updated_total: usize;
    {
        let mut stmt = tx.prepare(
            "UPDATE cities SET entity_type = ?1, entity_type_ids = ?2 WHERE id = ?3",
        )?;

        let pb = ProgressBar::new(types_map.len() as u64);
        pb.set_style(
            ProgressStyle::with_template(
                "  {msg} [{bar:40.cyan/blue}] {pos}/{len} ({percent}%) eta {eta}",
            )
            .unwrap()
            .progress_chars("=>-"),
        );
        pb.set_message("Updating cities");

        let mut updated = 0usize;
        for (qid, v) in &types_map {
            let types = v.get("types").and_then(|x| x.as_array());
            if types.is_none() {
                pb.inc(1);
                continue;
            }
            let arr = types.unwrap();

            let mut labels: Vec<String> = Vec::with_capacity(arr.len());
            let mut ids: Vec<String> = Vec::with_capacity(arr.len());
            for t in arr {
                let id = t.get("id").and_then(|x| x.as_str()).unwrap_or("").to_string();
                let label = t
                    .get("label")
                    .and_then(|x| x.as_str())
                    .unwrap_or("")
                    .to_string();
                if id.is_empty() {
                    continue;
                }
                ids.push(id);
                // fall back to id if label is empty — so the column is never silently lossy
                if label.is_empty() {
                    labels.push(ids.last().unwrap().clone());
                } else {
                    labels.push(label);
                }
            }

            if ids.is_empty() {
                pb.inc(1);
                continue;
            }

            let labels_joined = labels.join("|");
            let ids_joined = ids.join("|");
            let rows = stmt.execute(params![labels_joined, ids_joined, qid])?;
            updated += rows as usize;
            pb.inc(1);
        }
        pb.finish_with_message("Updating cities done");
        updated_total = updated;
    }
    tx.commit()?;
    log(&format!("[57] Updated {} city rows", updated_total));

    // Indexes for common filtering
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_cities_entity_type ON cities(entity_type);",
    )?;

    // Summary / sanity checks
    let total: i64 = conn.query_row("SELECT COUNT(*) FROM cities", [], |r| r.get(0))?;
    let with_type: i64 = conn.query_row(
        "SELECT COUNT(*) FROM cities WHERE entity_type IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    log(&format!(
        "[57] cities total={} with_entity_type={} coverage={:.1}%",
        total,
        with_type,
        100.0 * with_type as f64 / total.max(1) as f64
    ));

    // Top 20 entity_type strings by frequency
    log("[57] Top 20 entity_type values:");
    let mut stmt = conn.prepare(
        "SELECT entity_type, COUNT(*) c FROM cities
         WHERE entity_type IS NOT NULL
         GROUP BY entity_type ORDER BY c DESC LIMIT 20",
    )?;
    let rows: Vec<(String, i64)> = stmt
        .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?)))?
        .filter_map(|r| r.ok())
        .collect();
    for (et, c) in rows {
        let truncated: String = et.chars().take(120).collect();
        log(&format!("[57]   {:>8}  {}", c, truncated));
    }

    // Quick look at the examples we started with
    let mut stmt = conn.prepare(
        "SELECT id, name_en, entity_type FROM cities
         WHERE id IN ('Q100','Q30','Q771','Q60','Q90','Q1537')",
    )?;
    let rows: Vec<(String, Option<String>, Option<String>)> = stmt
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[57] Spot check:");
    for (id, name, et) in rows {
        log(&format!(
            "[57]   {} {} -> {}",
            id,
            name.as_deref().unwrap_or("?"),
            et.as_deref().unwrap_or("NULL")
        ));
    }

    log("=== Step 57 complete ===");
    Ok(())
}
