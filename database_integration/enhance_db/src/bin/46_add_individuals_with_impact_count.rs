/// Add `individuals_with_impact_count` column to `polities_cliopatria`.
/// Counts the number of individuals per polity that have a non-NULL impact_date
/// in individuals_cliopatria.
use anyhow::Result;
use rusqlite::{params, Connection};
use std::collections::HashMap;
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
    log("=== Step 46: Add individuals_with_impact_count to polities_cliopatria ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // ========================================================
    // PHASE 1: Add column if it doesn't exist
    // ========================================================
    log("[46] Phase 1: Adding column individuals_with_impact_count...");

    // Check if column already exists
    let col_exists: bool = {
        let mut stmt = conn.prepare("PRAGMA table_info(polities_cliopatria)")?;
        let cols: Vec<String> = stmt
            .query_map([], |r| r.get::<_, String>(1))?
            .filter_map(|r| r.ok())
            .collect();
        cols.contains(&"individuals_with_impact_count".to_string())
    };

    if !col_exists {
        conn.execute_batch(
            "ALTER TABLE polities_cliopatria ADD COLUMN individuals_with_impact_count INTEGER DEFAULT 0;",
        )?;
        log("[46] Column added.");
    } else {
        log("[46] Column already exists, will update values.");
    }

    // ========================================================
    // PHASE 2: Count individuals with impact_date per polity
    // ========================================================
    log("[46] Phase 2: Counting individuals with impact_date per polity...");
    let phase2_start = Instant::now();

    let mut counts: HashMap<i64, i64> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT polity_id, COUNT(*) FROM individuals_cliopatria
             WHERE impact_date IS NOT NULL
             GROUP BY polity_id",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((r.get::<_, i64>(0)?, r.get::<_, i64>(1)?))
        })?;
        for r in rows {
            let (pid, cnt) = r?;
            counts.insert(pid, cnt);
        }
    }
    log(&format!(
        "[46] Phase 2: {} polities with individuals having impact dates ({})",
        counts.len(),
        elapsed(phase2_start)
    ));

    // ========================================================
    // PHASE 3: Update polities_cliopatria
    // ========================================================
    log("[46] Phase 3: Updating polities_cliopatria...");

    // Reset all to 0 first
    conn.execute(
        "UPDATE polities_cliopatria SET individuals_with_impact_count = 0",
        [],
    )?;

    conn.execute_batch("BEGIN TRANSACTION;")?;
    {
        let mut stmt = conn.prepare_cached(
            "UPDATE polities_cliopatria SET individuals_with_impact_count = ?1 WHERE id = ?2",
        )?;
        for (pid, cnt) in &counts {
            stmt.execute(params![cnt, pid])?;
        }
    }
    conn.execute_batch("COMMIT;")?;
    log(&format!("[46] Phase 3: Updated {} polities.", counts.len()));

    // ========================================================
    // PHASE 4: Statistics
    // ========================================================
    log("[46] === Final Statistics ===");

    let total_polities: i64 = conn.query_row(
        "SELECT COUNT(*) FROM polities_cliopatria",
        [],
        |r| r.get(0),
    )?;
    let with_impact: i64 = conn.query_row(
        "SELECT COUNT(*) FROM polities_cliopatria WHERE individuals_with_impact_count > 0",
        [],
        |r| r.get(0),
    )?;
    let without: i64 = conn.query_row(
        "SELECT COUNT(*) FROM polities_cliopatria WHERE individuals_with_impact_count = 0",
        [],
        |r| r.get(0),
    )?;

    log(&format!("[46] Total polities: {}", total_polities));
    log(&format!("[46] Polities with impact-dated individuals: {}", with_impact));
    log(&format!("[46] Polities with zero: {}", without));

    // Top 15 polities by individuals_with_impact_count
    {
        let mut stmt = conn.prepare(
            "SELECT name, individuals_count, individuals_with_impact_count
             FROM polities_cliopatria
             ORDER BY individuals_with_impact_count DESC
             LIMIT 15",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, i64>(1)?,
                r.get::<_, i64>(2)?,
            ))
        })?;
        log("[46] Top 15 polities by individuals_with_impact_count:");
        for r in rows {
            let (name, total, with_impact) = r?;
            log(&format!(
                "[46]   {:<40}  total={:>8}  with_impact={:>8}",
                name, total, with_impact
            ));
        }
    }

    // Sample rows where the two counts differ significantly
    {
        let mut stmt = conn.prepare(
            "SELECT name, individuals_count, individuals_with_impact_count
             FROM polities_cliopatria
             WHERE individuals_count > 0
               AND individuals_with_impact_count < individuals_count
             ORDER BY (individuals_count - individuals_with_impact_count) DESC
             LIMIT 10",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, i64>(1)?,
                r.get::<_, i64>(2)?,
            ))
        })?;
        log("[46] Top 10 polities with largest gap (total vs with_impact):");
        for r in rows {
            let (name, total, with_impact) = r?;
            log(&format!(
                "[46]   {:<40}  total={:>8}  with_impact={:>8}  gap={:>8}",
                name,
                total,
                with_impact,
                total - with_impact
            ));
        }
    }

    log(&format!(
        "=== Step 46 complete ({}) ===",
        elapsed(total_start)
    ));
    Ok(())
}
