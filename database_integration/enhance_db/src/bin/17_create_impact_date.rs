/// Create individuals_impact_date table.
///
/// For each individual, compute an impact_date:
///   - birthdate + 35 years
///   - If birth+35 > deathdate, use deathdate
///   - If no birthdate, use deathdate
///   - If neither, skip
///
/// Columns: wikidata_id, name_en, impact_date, impact_date_precision, date_source
use anyhow::Result;
use rusqlite::{params, Connection};
use std::fs;
use std::io::Write;
use std::time::Instant;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const TASK_LOG: &str = "task.log";
const BATCH_SIZE: usize = 100_000;

fn log(msg: &str) {
    let now = chrono_now();
    let line = format!("[{}] {}", now, msg);
    println!("{}", line);
    let mut f = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(TASK_LOG)
        .unwrap();
    writeln!(f, "{}", line).unwrap();
}

fn chrono_now() -> String {
    let dur = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap();
    let secs = dur.as_secs();
    let hours = (secs % 86400) / 3600;
    let mins = (secs % 3600) / 60;
    let s = secs % 60;
    format!("{:02}:{:02}:{:02} UTC", hours, mins, s)
}

fn elapsed(start: Instant) -> String {
    let d = start.elapsed();
    let secs = d.as_secs();
    if secs < 60 {
        format!("{}s", secs)
    } else if secs < 3600 {
        format!("{}m {}s", secs / 60, secs % 60)
    } else {
        format!("{}h {}m {}s", secs / 3600, (secs % 3600) / 60, secs % 60)
    }
}

/// Parse a date string like "YYYY-MM-DD" or "-YYYY-MM-DD" (BCE).
/// Returns (year, month, day) or None if invalid.
fn parse_date(s: &str) -> Option<(i64, u32, u32)> {
    let s = s.trim();
    // Skip blank nodes like "_:bn..."
    if s.starts_with("_:") || s.is_empty() {
        return None;
    }

    let (negative, rest) = if let Some(stripped) = s.strip_prefix('-') {
        (true, stripped)
    } else {
        (false, s)
    };

    let parts: Vec<&str> = rest.splitn(3, '-').collect();
    if parts.len() < 3 {
        return None;
    }

    let year: i64 = parts[0].parse().ok()?;
    let month: u32 = parts[1].parse().ok()?;
    let day: u32 = parts[2].parse().ok()?;

    let year = if negative { -year } else { year };
    Some((year, month, day))
}

/// Format a date back to string. Handles negative years (BCE).
fn format_date(year: i64, month: u32, day: u32) -> String {
    if year < 0 {
        format!("-{:04}-{:02}-{:02}", -year, month, day)
    } else {
        format!("{:04}-{:02}-{:02}", year, month, day)
    }
}

/// Add 35 years to a date.
fn add_35_years(year: i64, month: u32, day: u32) -> (i64, u32, u32) {
    let new_year = year + 35;
    // Handle Feb 29 -> Feb 28 for non-leap years
    let new_day = if month == 2 && day == 29 && !is_leap_year(new_year) {
        28
    } else {
        day
    };
    (new_year, month, new_day)
}

fn is_leap_year(year: i64) -> bool {
    if year <= 0 {
        // Proleptic Gregorian: year 0 = 1 BCE, year -1 = 2 BCE
        let y = 1 - year; // convert to positive
        (y % 4 == 0) && ((y % 100 != 0) || (y % 400 == 0))
    } else {
        (year % 4 == 0) && ((year % 100 != 0) || (year % 400 == 0))
    }
}

/// Compare two dates: returns true if (y1,m1,d1) > (y2,m2,d2)
fn date_gt(y1: i64, m1: u32, d1: u32, y2: i64, m2: u32, d2: u32) -> bool {
    if y1 != y2 {
        return y1 > y2;
    }
    if m1 != m2 {
        return m1 > m2;
    }
    d1 > d2
}

fn main() -> Result<()> {
    let total_start = Instant::now();
    log("=== Step 17: Create individuals_impact_date table ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // Drop existing table if present
    conn.execute_batch("DROP TABLE IF EXISTS individuals_impact_date;")?;
    log("[17] Dropped existing individuals_impact_date (if any)");

    // Create the table
    conn.execute_batch(
        "CREATE TABLE individuals_impact_date (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            impact_date TEXT,
            impact_date_precision INTEGER,
            date_source TEXT
        );",
    )?;
    log("[17] Created individuals_impact_date table");

    // Count total individuals
    let total: i64 = conn.query_row("SELECT COUNT(*) FROM individuals", [], |r| r.get(0))?;
    log(&format!("[17] Total individuals to process: {}", total));

    // Read all individuals
    let step = Instant::now();
    log("[17] Reading individuals and computing impact dates...");

    let mut stmt = conn.prepare(
        "SELECT wikidata_id, name_en, birthdate, birthdate_precision, deathdate, deathdate_precision
         FROM individuals"
    )?;

    let mut rows_processed: i64 = 0;
    let mut rows_inserted: i64 = 0;
    let mut from_birth: i64 = 0;
    let mut from_death: i64 = 0;
    let mut skipped_no_date: i64 = 0;

    // Collect results in batches to insert
    let rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,                // wikidata_id
            row.get::<_, Option<String>>(1)?,         // name_en
            row.get::<_, Option<String>>(2)?,         // birthdate
            row.get::<_, Option<i64>>(3)?,            // birthdate_precision
            row.get::<_, Option<String>>(4)?,         // deathdate
            row.get::<_, Option<i64>>(5)?,            // deathdate_precision
        ))
    })?;

    // Begin transaction
    conn.execute_batch("BEGIN TRANSACTION;")?;

    {
        let mut insert_stmt = conn.prepare(
            "INSERT INTO individuals_impact_date (wikidata_id, name_en, impact_date, impact_date_precision, date_source)
             VALUES (?1, ?2, ?3, ?4, ?5)"
        )?;

        for row_result in rows {
            let (wikidata_id, name_en, birthdate, birth_precision, deathdate, death_precision) =
                row_result?;

            rows_processed += 1;

            let birth_parsed = birthdate.as_deref().and_then(parse_date);
            let death_parsed = deathdate.as_deref().and_then(parse_date);

            let result: Option<(String, Option<i64>, &str)> = match (birth_parsed, death_parsed) {
                (Some((by, bm, bd)), Some((dy, dm, dd))) => {
                    // Have both dates
                    let (iy, im, id) = add_35_years(by, bm, bd);
                    if date_gt(iy, im, id, dy, dm, dd) {
                        // birth+35 > death, use death date
                        Some((format_date(dy, dm, dd), death_precision, "deathdate"))
                    } else {
                        // Use birth+35
                        Some((format_date(iy, im, id), birth_precision, "birthdate"))
                    }
                }
                (Some((by, bm, bd)), None) => {
                    // Only birthdate
                    let (iy, im, id) = add_35_years(by, bm, bd);
                    Some((format_date(iy, im, id), birth_precision, "birthdate"))
                }
                (None, Some((dy, dm, dd))) => {
                    // Only deathdate
                    Some((format_date(dy, dm, dd), death_precision, "deathdate"))
                }
                (None, None) => {
                    // No dates
                    skipped_no_date += 1;
                    None
                }
            };

            if let Some((impact_date, precision, source)) = result {
                match source {
                    "birthdate" => from_birth += 1,
                    _ => from_death += 1,
                }
                insert_stmt.execute(params![
                    wikidata_id,
                    name_en,
                    impact_date,
                    precision,
                    source
                ])?;
                rows_inserted += 1;
            }

            if rows_processed % 1_000_000 == 0 {
                log(&format!(
                    "[17]   Processed {}/{} ({:.1}%) - inserted: {} ({}) ",
                    rows_processed,
                    total,
                    (rows_processed as f64 / total as f64) * 100.0,
                    rows_inserted,
                    elapsed(step)
                ));
            }
        }
    }

    conn.execute_batch("COMMIT;")?;
    log(&format!(
        "[17] All rows processed ({}) in {}",
        rows_processed,
        elapsed(step)
    ));

    // Create index
    let idx_start = Instant::now();
    log("[17] Creating indexes...");
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_impact_date ON individuals_impact_date(impact_date);
         CREATE INDEX IF NOT EXISTS idx_impact_wid ON individuals_impact_date(wikidata_id);"
    )?;
    log(&format!("[17] Indexes created ({})", elapsed(idx_start)));

    // Summary
    log(&format!("[17] === Summary ==="));
    log(&format!("[17]   Total processed: {}", rows_processed));
    log(&format!("[17]   Inserted: {}", rows_inserted));
    log(&format!("[17]   From birthdate+35: {}", from_birth));
    log(&format!("[17]   From deathdate: {}", from_death));
    log(&format!("[17]   Skipped (no dates): {}", skipped_no_date));

    // Verify
    let verify: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals_impact_date",
        [],
        |r| r.get(0),
    )?;
    log(&format!("[17]   Verified row count: {}", verify));

    // Sample output
    log("[17] Sample rows:");
    let mut sample = conn.prepare(
        "SELECT wikidata_id, name_en, impact_date, impact_date_precision, date_source
         FROM individuals_impact_date LIMIT 5"
    )?;
    let samples: Vec<(String, Option<String>, String, Option<i64>, String)> = sample
        .query_map([], |r| {
            Ok((
                r.get(0)?,
                r.get(1)?,
                r.get(2)?,
                r.get(3)?,
                r.get(4)?,
            ))
        })?
        .filter_map(|r| r.ok())
        .collect();
    for (wid, name, date, prec, src) in &samples {
        log(&format!(
            "[17]   {} | {} | {} | prec={:?} | src={}",
            wid,
            name.as_deref().unwrap_or("NULL"),
            date,
            prec,
            src
        ));
    }

    log(&format!(
        "=== Step 17 complete (total: {}) ===",
        elapsed(total_start)
    ));
    Ok(())
}
