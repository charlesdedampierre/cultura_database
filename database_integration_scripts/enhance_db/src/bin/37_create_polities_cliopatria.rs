/// Remove the count column from individuals_regions_cliopatria.
/// Create a new polities_cliopatria table with all polities from the Cliopatria DB
/// and the number of individuals gathered for each.
use anyhow::Result;
use rusqlite::{params, Connection};
use std::collections::HashMap;
use std::fs;
use std::io::Write;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const CLIO_DB_PATH: &str = "cliopatria_data/processing/data/cliopatria.db";
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
    log("=== Step 37: Remove count column & create polities_cliopatria table ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // ========================================================
    // PHASE 1: Remove count column from individuals_regions_cliopatria
    // ========================================================
    log("[37] Removing count column from individuals_regions_cliopatria...");

    // Check if count column exists
    let has_count: bool = {
        let mut stmt = conn.prepare("PRAGMA table_info(individuals_regions_cliopatria)")?;
        let cols: Vec<String> = stmt
            .query_map([], |r| r.get::<_, String>(1))?
            .filter_map(|r| r.ok())
            .collect();
        cols.contains(&"count".to_string())
    };

    if has_count {
        conn.execute_batch("ALTER TABLE individuals_regions_cliopatria DROP COLUMN count;")?;
        log("[37] Dropped count column");
    } else {
        log("[37] count column does not exist, skipping");
    }

    // ========================================================
    // PHASE 2: Read all polities from Cliopatria DB
    // ========================================================
    log("[37] Reading all polities from Cliopatria DB...");
    let clio_conn = Connection::open(CLIO_DB_PATH)?;

    struct Polity {
        id: i64,
        name: String,
        polity_type: Option<String>,
        wikipedia_url: Option<String>,
        wikidata_id: Option<String>,
    }

    let mut polities: Vec<Polity> = Vec::new();
    {
        let mut stmt = clio_conn.prepare(
            "SELECT id, name, type, wikipedia_url, wikidata_id FROM polities",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, Option<String>>(2)?,
                r.get::<_, Option<String>>(3)?,
                r.get::<_, Option<String>>(4)?,
            ))
        })?;
        for r in rows {
            let (id, name, polity_type, wikipedia_url, wikidata_id) = r?;
            polities.push(Polity {
                id,
                name: strip_parens(&name),
                polity_type,
                wikipedia_url,
                wikidata_id,
            });
        }
    }
    drop(clio_conn);
    log(&format!("[37] Total polities from Cliopatria: {}", polities.len()));

    // ========================================================
    // PHASE 3: Count individuals per polity_cliopatria
    // ========================================================
    log("[37] Counting individuals per polity...");
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
        "[37] Polities with individuals: {}",
        polity_counts.len()
    ));

    // ========================================================
    // PHASE 4: Create polities_cliopatria table
    // ========================================================
    log("[37] Creating polities_cliopatria table...");
    conn.execute_batch("DROP TABLE IF EXISTS polities_cliopatria;")?;
    conn.execute_batch(
        "CREATE TABLE polities_cliopatria (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT,
            wikipedia_url TEXT,
            wikidata_id TEXT,
            individuals_count INTEGER DEFAULT 0
        );",
    )?;

    conn.execute_batch("BEGIN TRANSACTION;")?;
    {
        let mut insert = conn.prepare(
            "INSERT INTO polities_cliopatria (id, name, type, wikipedia_url, wikidata_id, individuals_count)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
        )?;
        for p in &polities {
            let count = polity_counts.get(&p.name).copied().unwrap_or(0);
            insert.execute(params![
                p.id,
                p.name,
                p.polity_type,
                p.wikipedia_url,
                p.wikidata_id,
                count,
            ])?;
        }
    }
    conn.execute_batch("COMMIT;")?;

    // ========================================================
    // PHASE 5: Indexes and stats
    // ========================================================
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_pc_name ON polities_cliopatria(name);",
    )?;

    let total_polities: i64 =
        conn.query_row("SELECT COUNT(*) FROM polities_cliopatria", [], |r| r.get(0))?;
    let with_individuals: i64 = conn.query_row(
        "SELECT COUNT(*) FROM polities_cliopatria WHERE individuals_count > 0",
        [],
        |r| r.get(0),
    )?;
    let total_individuals: i64 = conn.query_row(
        "SELECT SUM(individuals_count) FROM polities_cliopatria",
        [],
        |r| r.get(0),
    )?;

    log("[37] === Final Statistics ===");
    log(&format!("[37] Total polities: {}", total_polities));
    log(&format!("[37] Polities with individuals: {}", with_individuals));
    log(&format!("[37] Polities without individuals: {}", total_polities - with_individuals));
    log(&format!("[37] Total individuals covered: {}", total_individuals));

    // Top 20
    let mut top = conn.prepare(
        "SELECT name, individuals_count FROM polities_cliopatria ORDER BY individuals_count DESC LIMIT 20",
    )?;
    let rows: Vec<(String, i64)> = top
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[37] Top 20 polities:");
    for (name, cnt) in &rows {
        log(&format!("[37]   {} -> {}", name, cnt));
    }

    log("=== Step 37 complete ===");
    Ok(())
}
