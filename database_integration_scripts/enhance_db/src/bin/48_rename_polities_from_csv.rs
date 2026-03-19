/// Rename polities in polities_cliopatria and cliopatria_polity_periods
/// to match the exact names from polities_cliopatria_enriched_JSB_iteration.csv.
/// Merges on polity id.
use anyhow::Result;
use rusqlite::{params, Connection};
use std::collections::HashMap;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::time::Instant;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const CSV_PATH: &str =
    "data/manual_changes_cliopatria_data/polities_cliopatria_enriched_JSB_iteration.csv";
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

fn elapsed(start: Instant) -> String {
    let s = start.elapsed().as_secs();
    if s < 60 {
        format!("{}s", s)
    } else {
        format!("{}m {}s", s / 60, s % 60)
    }
}

fn main() -> Result<()> {
    let _ = fs::remove_file(TASK_LOG);
    let total_start = Instant::now();
    log("=== Step 48: Rename polities from CSV ===");

    // ========================================================
    // PHASE 1: Read CSV — id,vname mapping
    // ========================================================
    log("[48] Phase 1: Reading CSV...");
    let file = fs::File::open(CSV_PATH)?;
    let reader = BufReader::new(file);
    let mut csv_names: HashMap<i64, String> = HashMap::new();

    let mut lines = reader.lines();
    let header = lines.next().unwrap()?;
    // Find column indices
    let cols: Vec<&str> = header.split(',').collect();
    let id_idx = cols.iter().position(|&c| c == "id").expect("no id column");
    let name_idx = cols.iter().position(|&c| c == "vname").expect("no vname column");

    for line in lines {
        let line = line?;
        // Simple CSV parse (no quoted commas in these fields)
        let fields: Vec<&str> = line.split(',').collect();
        if fields.len() > name_idx {
            let id: i64 = fields[id_idx].parse()?;
            let name = fields[name_idx].to_string();
            csv_names.insert(id, name);
        }
    }
    log(&format!("[48] Phase 1: Read {} entries from CSV", csv_names.len()));

    // ========================================================
    // PHASE 2: Find differences and update
    // ========================================================
    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // polities_cliopatria
    log("[48] Phase 2a: Updating polities_cliopatria...");
    let mut pc_updates: Vec<(i64, String, String)> = Vec::new();
    {
        let mut stmt = conn.prepare("SELECT id, name FROM polities_cliopatria")?;
        let rows = stmt.query_map([], |r| {
            Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?))
        })?;
        for r in rows {
            let (id, db_name) = r?;
            if let Some(csv_name) = csv_names.get(&id) {
                if &db_name != csv_name {
                    pc_updates.push((id, db_name, csv_name.clone()));
                }
            }
        }
    }

    log(&format!(
        "[48] Phase 2a: {} names to update in polities_cliopatria",
        pc_updates.len()
    ));
    for (id, old, new) in &pc_updates {
        log(&format!("[48]   id={}: '{}' -> '{}'", id, old, new));
    }

    conn.execute_batch("BEGIN TRANSACTION;")?;
    {
        let mut stmt =
            conn.prepare_cached("UPDATE polities_cliopatria SET name = ?1 WHERE id = ?2")?;
        for (id, _, new_name) in &pc_updates {
            stmt.execute(params![new_name, id])?;
        }
    }
    conn.execute_batch("COMMIT;")?;

    // cliopatria_polity_periods
    log("[48] Phase 2b: Updating cliopatria_polity_periods...");
    let mut pp_updates: Vec<(i64, String, String)> = Vec::new();
    {
        let mut stmt = conn
            .prepare("SELECT DISTINCT polity_id, polity_name FROM cliopatria_polity_periods")?;
        let rows = stmt.query_map([], |r| {
            Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?))
        })?;
        for r in rows {
            let (id, db_name) = r?;
            if let Some(csv_name) = csv_names.get(&id) {
                if &db_name != csv_name {
                    pp_updates.push((id, db_name, csv_name.clone()));
                }
            }
        }
    }

    log(&format!(
        "[48] Phase 2b: {} names to update in cliopatria_polity_periods",
        pp_updates.len()
    ));
    for (id, old, new) in &pp_updates {
        log(&format!("[48]   polity_id={}: '{}' -> '{}'", id, old, new));
    }

    conn.execute_batch("BEGIN TRANSACTION;")?;
    {
        let mut stmt = conn.prepare_cached(
            "UPDATE cliopatria_polity_periods SET polity_name = ?1 WHERE polity_id = ?2",
        )?;
        for (id, _, new_name) in &pp_updates {
            stmt.execute(params![new_name, id])?;
        }
    }
    conn.execute_batch("COMMIT;")?;

    // ========================================================
    // PHASE 3: Verification
    // ========================================================
    log("[48] Phase 3: Verification...");

    let mut mismatches = 0;
    {
        let mut stmt = conn.prepare("SELECT id, name FROM polities_cliopatria")?;
        let rows = stmt.query_map([], |r| {
            Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?))
        })?;
        for r in rows {
            let (id, db_name) = r?;
            if let Some(csv_name) = csv_names.get(&id) {
                if &db_name != csv_name {
                    mismatches += 1;
                    log(&format!(
                        "[48] MISMATCH: id={} db='{}' csv='{}'",
                        id, db_name, csv_name
                    ));
                }
            }
        }
    }
    log(&format!(
        "[48] Remaining mismatches in polities_cliopatria: {}",
        mismatches
    ));

    let mut pp_mismatches = 0;
    {
        let mut stmt = conn
            .prepare("SELECT DISTINCT polity_id, polity_name FROM cliopatria_polity_periods")?;
        let rows = stmt.query_map([], |r| {
            Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?))
        })?;
        for r in rows {
            let (id, db_name) = r?;
            if let Some(csv_name) = csv_names.get(&id) {
                if &db_name != csv_name {
                    pp_mismatches += 1;
                    log(&format!(
                        "[48] MISMATCH: polity_id={} db='{}' csv='{}'",
                        id, db_name, csv_name
                    ));
                }
            }
        }
    }
    log(&format!(
        "[48] Remaining mismatches in cliopatria_polity_periods: {}",
        pp_mismatches
    ));

    log(&format!("=== Step 48 complete ({}) ===", elapsed(total_start)));
    Ok(())
}
