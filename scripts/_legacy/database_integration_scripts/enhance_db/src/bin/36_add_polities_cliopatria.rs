/// Add polity_cliopatria column to individuals_regions_cliopatria.
/// Matches individuals to Cliopatria polities by wikipedia_url.
/// Strips parentheses from polity names.
/// Then adds a count column with the number of individuals per polity.
use anyhow::Result;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection};
use std::collections::HashMap;
use std::fs;
use std::io::Write;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const CLIO_DB_PATH: &str = "cliopatria_data/processing/data/cliopatria.db";
const TASK_LOG: &str = "task.log";
const BATCH_SIZE: usize = 50_000;

fn log(msg: &str) {
    println!("{}", msg);
    let mut f = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(TASK_LOG)
        .unwrap();
    writeln!(f, "{}", msg).unwrap();
}

/// Remove surrounding parentheses from polity name: "(British Empire)" -> "British Empire"
fn strip_parens(name: &str) -> String {
    let trimmed = name.trim();
    if trimmed.starts_with('(') && trimmed.ends_with(')') {
        trimmed[1..trimmed.len() - 1].to_string()
    } else {
        trimmed.to_string()
    }
}

fn main() -> Result<()> {
    let _ = fs::remove_file(TASK_LOG);
    log("=== Step 36: Add polities_cliopatria to individuals_regions_cliopatria ===");

    // ========================================================
    // PHASE 1: Build polity lookup from Cliopatria DB
    // ========================================================
    log("[36] Reading Cliopatria polities...");
    let clio_conn = Connection::open(CLIO_DB_PATH)?;
    let mut url_to_polity: HashMap<String, String> = HashMap::new();
    {
        let mut stmt =
            clio_conn.prepare("SELECT name, wikipedia_url FROM polities WHERE wikipedia_url IS NOT NULL")?;
        let rows = stmt.query_map([], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
        })?;
        for r in rows {
            let (name, url) = r?;
            let clean_name = strip_parens(&name);
            url_to_polity.insert(url, clean_name);
        }
    }
    drop(clio_conn);
    log(&format!(
        "[36] Cliopatria polity lookup: {} entries",
        url_to_polity.len()
    ));

    // ========================================================
    // PHASE 2: Add column to individuals_regions_cliopatria
    // ========================================================
    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // Check if column already exists
    let has_column: bool = {
        let mut stmt = conn.prepare("PRAGMA table_info(individuals_regions_cliopatria)")?;
        let cols: Vec<String> = stmt
            .query_map([], |r| r.get::<_, String>(1))?
            .filter_map(|r| r.ok())
            .collect();
        cols.contains(&"polity_cliopatria".to_string())
    };

    if !has_column {
        log("[36] Adding polity_cliopatria column...");
        conn.execute_batch(
            "ALTER TABLE individuals_regions_cliopatria ADD COLUMN polity_cliopatria TEXT;",
        )?;
    } else {
        log("[36] polity_cliopatria column already exists, resetting...");
        conn.execute_batch(
            "UPDATE individuals_regions_cliopatria SET polity_cliopatria = NULL;",
        )?;
    }

    // Check if count column already exists
    let has_count: bool = {
        let mut stmt = conn.prepare("PRAGMA table_info(individuals_regions_cliopatria)")?;
        let cols: Vec<String> = stmt
            .query_map([], |r| r.get::<_, String>(1))?
            .filter_map(|r| r.ok())
            .collect();
        cols.contains(&"count".to_string())
    };

    if !has_count {
        log("[36] Adding count column...");
        conn.execute_batch(
            "ALTER TABLE individuals_regions_cliopatria ADD COLUMN count INTEGER;",
        )?;
    } else {
        log("[36] count column already exists, resetting...");
        conn.execute_batch("UPDATE individuals_regions_cliopatria SET count = NULL;")?;
    }

    // ========================================================
    // PHASE 3: Update polity_cliopatria by matching URL
    // ========================================================
    let total: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals_regions_cliopatria",
        [],
        |r| r.get(0),
    )?;
    log(&format!("[36] Total rows to process: {}", total));

    let pb = ProgressBar::new(total as u64);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{msg} [{bar:40}] {pos}/{len} ({eta})")
            .unwrap(),
    );
    pb.set_message("Matching polities");

    let mut offset: i64 = 0;
    let mut matched = 0u64;
    let mut unmatched = 0u64;

    loop {
        let mut batch: Vec<(String, String)> = Vec::with_capacity(BATCH_SIZE);
        {
            let mut stmt = conn.prepare_cached(
                "SELECT wikidata_id, url FROM individuals_regions_cliopatria
                 ORDER BY rowid
                 LIMIT ?1 OFFSET ?2",
            )?;
            let rows = stmt.query_map(params![BATCH_SIZE as i64, offset], |r| {
                Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
            })?;
            for r in rows {
                batch.push(r?);
            }
        }

        if batch.is_empty() {
            break;
        }

        conn.execute_batch("BEGIN TRANSACTION;")?;
        {
            let mut update = conn.prepare_cached(
                "UPDATE individuals_regions_cliopatria SET polity_cliopatria = ?1 WHERE wikidata_id = ?2",
            )?;

            for (wikidata_id, url) in &batch {
                if let Some(polity) = url_to_polity.get(url.as_str()) {
                    update.execute(params![polity, wikidata_id])?;
                    matched += 1;
                } else {
                    unmatched += 1;
                }
            }
        }
        conn.execute_batch("COMMIT;")?;

        pb.inc(batch.len() as u64);
        offset += batch.len() as i64;

        if offset % 500_000 < BATCH_SIZE as i64 {
            log(&format!(
                "[36] Progress: {}/{} processed, {} matched, {} unmatched",
                offset, total, matched, unmatched
            ));
        }
    }
    pb.finish();

    log(&format!(
        "[36] Polity matching done: {} matched, {} unmatched",
        matched, unmatched
    ));

    // ========================================================
    // PHASE 4: Compute counts per polity and update
    // ========================================================
    log("[36] Computing individuals count per polity...");
    let mut polity_counts: HashMap<String, i64> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT polity_cliopatria, COUNT(*) FROM individuals_regions_cliopatria
             WHERE polity_cliopatria IS NOT NULL
             GROUP BY polity_cliopatria",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?))
        })?;
        for r in rows {
            let (polity, cnt) = r?;
            polity_counts.insert(polity, cnt);
        }
    }
    log(&format!(
        "[36] Distinct polities with individuals: {}",
        polity_counts.len()
    ));

    log("[36] Updating count column...");
    conn.execute_batch("BEGIN TRANSACTION;")?;
    {
        let mut update = conn.prepare(
            "UPDATE individuals_regions_cliopatria SET count = ?1 WHERE polity_cliopatria = ?2",
        )?;
        for (polity, cnt) in &polity_counts {
            update.execute(params![cnt, polity])?;
        }
    }
    conn.execute_batch("COMMIT;")?;

    // ========================================================
    // PHASE 5: Create index and final stats
    // ========================================================
    log("[36] Creating indexes...");
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_irc_polity ON individuals_regions_cliopatria(polity_cliopatria);",
    )?;

    let total_with_polity: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals_regions_cliopatria WHERE polity_cliopatria IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    let total_without: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals_regions_cliopatria WHERE polity_cliopatria IS NULL",
        [],
        |r| r.get(0),
    )?;

    log("[36] === Final Statistics ===");
    log(&format!("[36] Total rows: {}", total));
    log(&format!("[36] With polity_cliopatria: {}", total_with_polity));
    log(&format!("[36] Without polity_cliopatria: {}", total_without));

    // Top 20 polities
    let mut top = conn.prepare(
        "SELECT polity_cliopatria, count FROM individuals_regions_cliopatria
         WHERE polity_cliopatria IS NOT NULL
         GROUP BY polity_cliopatria
         ORDER BY count DESC LIMIT 20",
    )?;
    let rows: Vec<(String, i64)> = top
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[36] Top 20 polities by individual count:");
    for (polity, cnt) in &rows {
        log(&format!("[36]   {} -> {}", polity, cnt));
    }

    log("=== Step 36 complete ===");
    Ok(())
}
