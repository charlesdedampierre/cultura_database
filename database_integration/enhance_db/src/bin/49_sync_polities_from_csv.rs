/// Sync polities_cliopatria and cliopatria_polity_periods with the CSV:
///  1. Update wikipedia_url and wikidata_id from CSV where they differ
///  2. Apply manual name renames on both tables
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

struct CsvRow {
    id: i64,
    vname: String,
    wikipedia_url: String,
    wikidata_id: String,
}

fn parse_csv_line(line: &str, id_idx: usize, name_idx: usize, url_idx: usize, wk_idx: usize) -> Option<CsvRow> {
    let fields: Vec<&str> = line.split(',').collect();
    let max_idx = *[id_idx, name_idx, url_idx, wk_idx].iter().max().unwrap();
    if fields.len() <= max_idx {
        return None;
    }
    let id: i64 = fields[id_idx].parse().ok()?;
    Some(CsvRow {
        id,
        vname: fields[name_idx].to_string(),
        wikipedia_url: fields[url_idx].to_string(),
        wikidata_id: fields[wk_idx].to_string(),
    })
}

fn main() -> Result<()> {
    let _ = fs::remove_file(TASK_LOG);
    let total_start = Instant::now();
    log("=== Step 49: Sync URLs, Wikidata IDs, and rename polities ===");

    // ========================================================
    // PHASE 1: Read CSV
    // ========================================================
    log("[49] Phase 1: Reading CSV...");
    let file = fs::File::open(CSV_PATH)?;
    let reader = BufReader::new(file);
    let mut csv_rows: HashMap<i64, CsvRow> = HashMap::new();

    let mut lines = reader.lines();
    let header = lines.next().unwrap()?;
    let cols: Vec<&str> = header.split(',').collect();
    let id_idx = cols.iter().position(|&c| c == "id").expect("no id column");
    let name_idx = cols.iter().position(|&c| c == "vname").expect("no vname column");
    let url_idx = cols.iter().position(|&c| c == "wikipedia_url").expect("no wikipedia_url column");
    let wk_idx = cols.iter().position(|&c| c == "wikidata_id").expect("no wikidata_id column");

    for line in lines {
        let line = line?;
        if let Some(row) = parse_csv_line(&line, id_idx, name_idx, url_idx, wk_idx) {
            csv_rows.insert(row.id, row);
        }
    }
    log(&format!("[49] Phase 1: Read {} entries from CSV", csv_rows.len()));

    // ========================================================
    // PHASE 2: Sync wikipedia_url and wikidata_id
    // ========================================================
    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    log("[49] Phase 2: Syncing wikipedia_url and wikidata_id...");

    let mut url_updates: Vec<(i64, String, String, String)> = Vec::new();
    let mut wk_updates: Vec<(i64, String, String, String)> = Vec::new();
    {
        let mut stmt =
            conn.prepare("SELECT id, name, wikipedia_url, wikidata_id FROM polities_cliopatria")?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, Option<String>>(2)?,
                r.get::<_, Option<String>>(3)?,
            ))
        })?;
        for r in rows {
            let (id, name, db_url, db_wk) = r?;
            if let Some(csv) = csv_rows.get(&id) {
                let db_url_str = db_url.unwrap_or_default();
                let db_wk_str = db_wk.unwrap_or_default();
                if !csv.wikipedia_url.is_empty() && csv.wikipedia_url != db_url_str {
                    url_updates.push((id, name.clone(), db_url_str, csv.wikipedia_url.clone()));
                }
                if !csv.wikidata_id.is_empty() && csv.wikidata_id != db_wk_str {
                    wk_updates.push((id, name.clone(), db_wk_str, csv.wikidata_id.clone()));
                }
            }
        }
    }

    log(&format!("[49] Wikipedia URLs to update: {}", url_updates.len()));
    for (id, name, old, new) in &url_updates {
        log(&format!("[49]   id={}: {} | '{}' -> '{}'", id, name, old, new));
    }

    log(&format!("[49] Wikidata IDs to update: {}", wk_updates.len()));
    for (id, name, old, new) in &wk_updates {
        log(&format!("[49]   id={}: {} | '{}' -> '{}'", id, name, old, new));
    }

    conn.execute_batch("BEGIN TRANSACTION;")?;
    {
        let mut stmt = conn
            .prepare_cached("UPDATE polities_cliopatria SET wikipedia_url = ?1 WHERE id = ?2")?;
        for (id, _, _, new_url) in &url_updates {
            stmt.execute(params![new_url, id])?;
        }
    }
    {
        let mut stmt = conn
            .prepare_cached("UPDATE polities_cliopatria SET wikidata_id = ?1 WHERE id = ?2")?;
        for (id, _, _, new_wk) in &wk_updates {
            stmt.execute(params![new_wk, id])?;
        }
    }
    conn.execute_batch("COMMIT;")?;
    log("[49] Phase 2: Done.");

    // ========================================================
    // PHASE 3: Manual name renames
    // ========================================================
    log("[49] Phase 3: Applying manual name renames...");

    let renames: Vec<(&str, &str)> = vec![
        ("Iragi Republic", "Iraqi Republic"),
        ("Vietnam", "Socialist Republic of Vietnam"),
        ("Champa", "Chámpa"),
        ("Great Việt", "Đại Việt"),
        ("French Colonial Vietnam", "French Indochina"),
        ("Kingdom of Dambadaneiya", "Kingdom of Dambadeniya"),
        ("Gurkha Kingdom", "Gorkha Kingdom"),
    ];

    conn.execute_batch("BEGIN TRANSACTION;")?;
    for (old_name, new_name) in &renames {
        // Update polities_cliopatria
        let pc_count = conn.execute(
            "UPDATE polities_cliopatria SET name = ?1 WHERE name = ?2",
            params![new_name, old_name],
        )?;

        // Update cliopatria_polity_periods
        let pp_count = conn.execute(
            "UPDATE cliopatria_polity_periods SET polity_name = ?1 WHERE polity_name = ?2",
            params![new_name, old_name],
        )?;

        if pc_count > 0 || pp_count > 0 {
            log(&format!(
                "[49]   '{}' -> '{}' (polities: {}, periods: {})",
                old_name, new_name, pc_count, pp_count
            ));
        } else {
            log(&format!(
                "[49]   '{}' -> '{}' — not found (already renamed?)",
                old_name, new_name
            ));
        }
    }
    conn.execute_batch("COMMIT;")?;
    log("[49] Phase 3: Done.");

    // ========================================================
    // PHASE 4: Verification
    // ========================================================
    log("[49] Phase 4: Verification...");

    // Check the renamed entries exist
    for (_, new_name) in &renames {
        let count: i64 = conn.query_row(
            "SELECT COUNT(*) FROM polities_cliopatria WHERE name = ?1",
            params![new_name],
            |r| r.get(0),
        )?;
        let pp_count: i64 = conn.query_row(
            "SELECT COUNT(*) FROM cliopatria_polity_periods WHERE polity_name = ?1",
            params![new_name],
            |r| r.get(0),
        )?;
        log(&format!(
            "[49]   '{}': polities={}, periods={}",
            new_name, count, pp_count
        ));
    }

    // Verify URL/Wikidata sync
    let mut remaining_url = 0i64;
    let mut remaining_wk = 0i64;
    {
        let mut stmt =
            conn.prepare("SELECT id, wikipedia_url, wikidata_id FROM polities_cliopatria")?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, Option<String>>(1)?,
                r.get::<_, Option<String>>(2)?,
            ))
        })?;
        for r in rows {
            let (id, db_url, db_wk) = r?;
            if let Some(csv) = csv_rows.get(&id) {
                let db_url_str = db_url.unwrap_or_default();
                let db_wk_str = db_wk.unwrap_or_default();
                if !csv.wikipedia_url.is_empty() && csv.wikipedia_url != db_url_str {
                    remaining_url += 1;
                }
                if !csv.wikidata_id.is_empty() && csv.wikidata_id != db_wk_str {
                    remaining_wk += 1;
                }
            }
        }
    }
    log(&format!(
        "[49] Remaining URL mismatches: {}, Wikidata mismatches: {}",
        remaining_url, remaining_wk
    ));

    log(&format!("=== Step 49 complete ({}) ===", elapsed(total_start)));
    Ok(())
}
