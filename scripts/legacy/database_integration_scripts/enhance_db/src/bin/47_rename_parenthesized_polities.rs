/// Rename polities in polities_cliopatria to match the original GeoJSON names.
/// In the original GeoJSON (cliopatria_polities_only.geojson), some polity names
/// are wrapped in parentheses like "(Abbasid Caliphate)". The cliopatria_polity_periods
/// table kept these original names, but polities_cliopatria had them stripped.
/// This script restores the parenthesized names in polities_cliopatria to match
/// the original data.
use anyhow::Result;
use rusqlite::{params, Connection};
use std::fs;
use std::io::Write;
use std::time::Instant;

const DB_PATH: &str = "data/humans_clean.sqlite3";
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
    } else if s < 3600 {
        format!("{}m {}s", s / 60, s % 60)
    } else {
        format!("{}h {}m {}s", s / 3600, (s % 3600) / 60, s % 60)
    }
}

fn main() -> Result<()> {
    let _ = fs::remove_file(TASK_LOG);
    let total_start = Instant::now();
    log("=== Step 47: Rename polities to match original GeoJSON parenthesized names ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // ========================================================
    // PHASE 1: Find polities that need parentheses restored
    // ========================================================
    log("[47] Phase 1: Finding polities with parenthesized names in cliopatria_polity_periods...");

    // Use cliopatria_polity_periods as the source of truth for the original names.
    // Find distinct polity_id + polity_name where the name is wrapped in parentheses,
    // and update polities_cliopatria.name accordingly.
    let mut stmt = conn.prepare(
        "SELECT DISTINCT cpp.polity_id, cpp.polity_name, pc.name
         FROM cliopatria_polity_periods cpp
         JOIN polities_cliopatria pc ON cpp.polity_id = pc.id
         WHERE SUBSTR(cpp.polity_name, 1, 1) = '('
           AND SUBSTR(cpp.polity_name, LENGTH(cpp.polity_name), 1) = ')'
           AND LENGTH(cpp.polity_name) > 2
           AND INSTR(SUBSTR(cpp.polity_name, 2, LENGTH(cpp.polity_name) - 2), '(') = 0
           AND pc.name != cpp.polity_name
         ORDER BY pc.name",
    )?;

    let mappings: Vec<(i64, String, String)> = stmt
        .query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
            ))
        })?
        .filter_map(|r| r.ok())
        .collect();

    log(&format!(
        "[47] Phase 1: Found {} polities to rename in polities_cliopatria",
        mappings.len()
    ));

    // Show all renames
    for (_, new_name, old_name) in &mappings {
        log(&format!("[47]   '{}' -> '{}'", old_name, new_name));
    }

    // ========================================================
    // PHASE 2: Update polities_cliopatria
    // ========================================================
    log("[47] Phase 2: Updating polities_cliopatria...");
    let phase2_start = Instant::now();

    conn.execute_batch("BEGIN TRANSACTION;")?;
    {
        let mut update_stmt = conn.prepare_cached(
            "UPDATE polities_cliopatria SET name = ?1 WHERE id = ?2",
        )?;
        for (polity_id, new_name, _) in &mappings {
            update_stmt.execute(params![new_name, polity_id])?;
        }
    }
    conn.execute_batch("COMMIT;")?;

    log(&format!(
        "[47] Phase 2: Updated {} polities in polities_cliopatria ({})",
        mappings.len(),
        elapsed(phase2_start)
    ));

    // ========================================================
    // PHASE 3: Verification
    // ========================================================
    log("[47] Phase 3: Verification...");

    // Check consistency: all polity_names in cliopatria_polity_periods should now match polities_cliopatria.name
    let mismatches: i64 = conn.query_row(
        "SELECT COUNT(DISTINCT cpp.polity_name)
         FROM cliopatria_polity_periods cpp
         JOIN polities_cliopatria pc ON cpp.polity_id = pc.id
         WHERE cpp.polity_name != pc.name",
        [],
        |r| r.get(0),
    )?;
    log(&format!(
        "[47] Name mismatches between cliopatria_polity_periods and polities_cliopatria: {}",
        mismatches
    ));

    if mismatches > 0 {
        let mut stmt = conn.prepare(
            "SELECT DISTINCT cpp.polity_name, pc.name
             FROM cliopatria_polity_periods cpp
             JOIN polities_cliopatria pc ON cpp.polity_id = pc.id
             WHERE cpp.polity_name != pc.name
             ORDER BY pc.name
             LIMIT 10",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
        })?;
        log("[47] Sample remaining mismatches:");
        for r in rows {
            let (pp_name, pc_name) = r?;
            log(&format!(
                "[47]   polity_periods: '{}' vs polities: '{}'",
                pp_name, pc_name
            ));
        }
    }

    // Sample of renamed polities
    let mut stmt = conn.prepare(
        "SELECT name FROM polities_cliopatria
         WHERE SUBSTR(name, 1, 1) = '(' AND SUBSTR(name, LENGTH(name), 1) = ')'
         ORDER BY name LIMIT 10",
    )?;
    let rows = stmt.query_map([], |r| r.get::<_, String>(0))?;
    log("[47] Sample parenthesized names in polities_cliopatria after update:");
    for r in rows {
        log(&format!("[47]   {}", r?));
    }

    log(&format!(
        "=== Step 47 complete ({}) ===",
        elapsed(total_start)
    ));
    Ok(())
}
