/// Fix encoding issues in the database.
/// Detects and fixes mojibake (double-encoded UTF-8) in all text columns.
/// Uses batched processing to avoid OOM on large tables.
use anyhow::Result;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection};
use std::fs;
use std::io::Write;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const TASK_LOG: &str = "task.log";
const BATCH_SIZE: i64 = 500_000;

fn log(msg: &str) {
    println!("{}", msg);
    let mut f = fs::OpenOptions::new()
        .append(true)
        .open(TASK_LOG)
        .unwrap();
    writeln!(f, "{}", msg).unwrap();
}

/// Attempt to fix mojibake by interpreting the string as Latin-1 encoded UTF-8.
fn fix_mojibake(input: &str) -> Option<String> {
    let has_mojibake = input.chars().any(|c| {
        let cp = c as u32;
        (0xC0..=0xFF).contains(&cp)
    });

    if !has_mojibake {
        return None;
    }

    // Check all chars fit in a single byte (Latin-1 range)
    if input.chars().any(|c| c as u32 > 0xFF) {
        return None;
    }

    let bytes: Vec<u8> = input.chars().map(|c| c as u32 as u8).collect();

    match String::from_utf8(bytes) {
        Ok(fixed) if fixed != input => Some(fixed),
        _ => None,
    }
}

/// Fix encoding in a table column using batched SQL processing.
/// For large tables, uses rowid-based pagination to avoid loading all data into memory.
fn fix_table_column_batched(conn: &Connection, table: &str, pk_col: &str, text_col: &str) -> Result<usize> {
    // First get total count
    let total: i64 = conn.query_row(
        &format!("SELECT COUNT(*) FROM {} WHERE {} IS NOT NULL", table, text_col),
        [],
        |row| row.get(0),
    )?;

    if total == 0 {
        return Ok(0);
    }

    let num_batches = (total + BATCH_SIZE - 1) / BATCH_SIZE;
    let pb = ProgressBar::new(num_batches as u64);
    pb.set_style(ProgressStyle::default_bar()
        .template(&format!("  {}.{} [{{bar:30}}] {{pos}}/{{len}} batches", table, text_col))
        .unwrap());

    let mut fixed_count = 0usize;
    let mut offset = 0i64;

    let update_sql = format!(
        "UPDATE {} SET {} = ?1 WHERE {} = ?2",
        table, text_col, pk_col
    );

    loop {
        // Read a batch
        let query = format!(
            "SELECT {}, {} FROM {} WHERE {} IS NOT NULL LIMIT {} OFFSET {}",
            pk_col, text_col, table, text_col, BATCH_SIZE, offset
        );
        let mut stmt = conn.prepare(&query)?;
        let batch: Vec<(String, String)> = stmt
            .query_map([], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
            })?
            .filter_map(|r| r.ok())
            .collect();

        if batch.is_empty() {
            break;
        }

        // Find entries that need fixing
        let fixes: Vec<(String, String)> = batch
            .iter()
            .filter_map(|(pk, value)| {
                fix_mojibake(value).map(|fixed| (pk.clone(), fixed))
            })
            .collect();

        // Apply fixes in a transaction
        if !fixes.is_empty() {
            conn.execute_batch("BEGIN TRANSACTION;")?;
            let mut update_stmt = conn.prepare(&update_sql)?;
            for (pk, fixed) in &fixes {
                update_stmt.execute(params![fixed, pk])?;
            }
            conn.execute_batch("COMMIT;")?;
            fixed_count += fixes.len();
        }

        offset += BATCH_SIZE;
        pb.inc(1);

        if batch.len() < BATCH_SIZE as usize {
            break;
        }
    }

    pb.finish_and_clear();
    Ok(fixed_count)
}

fn main() -> Result<()> {
    log("[DB] 02: Fixing encoding issues (batched)...");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-500000;")?;

    // Small tables first, then large ones
    let tables: Vec<(&str, &str, Vec<&str>)> = vec![
        ("occupations", "id", vec!["name_en", "meta_occupation", "description_en", "instance_of"]),
        ("nationalities", "name_en", vec!["description_en", "instance_of"]),
        ("identifier_types", "property_id", vec!["name_en", "description", "issuer_name", "country_name"]),
        ("properties_definition", "property_id", vec!["property_name", "description"]),
        ("cities", "id", vec!["name_en", "country_name", "continent"]),
        ("sitelinks", "id", vec!["title"]),
        ("identifiers", "wikidata_id", vec!["individual_name", "identifier_name"]),
        ("individuals", "wikidata_id", vec!["name_en", "description_en", "nationalities_en", "birthcity_en", "deathcity_en", "occupations_en"]),
    ];

    let mut total_fixed = 0usize;
    for (table, pk, columns) in &tables {
        for col in columns {
            log(&format!("[DB] Processing {}.{}...", table, col));
            match fix_table_column_batched(&conn, table, pk, col) {
                Ok(count) => {
                    if count > 0 {
                        log(&format!("[DB]   Fixed {} entries in {}.{}", count, table, col));
                    }
                    total_fixed += count;
                }
                Err(e) => {
                    log(&format!("[DB]   Error fixing {}.{}: {}", table, col, e));
                }
            }
        }
    }

    // Special handling: fix nationalities where name_en is the PK
    log("[DB] Fixing nationality name_en (primary key) encoding...");
    {
        let mut stmt = conn.prepare("SELECT name_en, wikidata_id FROM nationalities WHERE name_en IS NOT NULL")?;
        let rows: Vec<(String, Option<String>)> = stmt
            .query_map([], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, Option<String>>(1)?))
            })?
            .filter_map(|r| r.ok())
            .collect();

        for (name, _wikidata_id) in &rows {
            if let Some(fixed) = fix_mojibake(name) {
                let exists: bool = conn.query_row(
                    "SELECT COUNT(*) FROM nationalities WHERE name_en = ?1",
                    params![fixed],
                    |row| row.get::<_, i64>(0),
                ).map(|c| c > 0).unwrap_or(false);

                if !exists {
                    conn.execute(
                        "UPDATE nationalities SET name_en = ?1 WHERE name_en = ?2",
                        params![fixed, name],
                    )?;
                    total_fixed += 1;
                    log(&format!("[DB]   Fixed nationality name: '{}' -> '{}'", name, fixed));
                }
            }
        }
    }

    log(&format!("[DB] 02: Done. Fixed {} encoding issues total.", total_fixed));
    Ok(())
}
