/// Add region and macro_region columns to individuals_countries.
/// For each individual, look up their impact_date and match with
/// regions table date ranges. Multiple regions/macro_regions are
/// stored as semicolon-separated text.
use anyhow::Result;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection};
use std::collections::HashMap;
use std::fs;
use std::io::Write;

const DB_PATH: &str = "data/humans_clean.sqlite3";
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

/// Parse a year from a date string like '1972-04-11' or '-0500-01-01'
fn parse_year(date_str: &str) -> Option<i32> {
    if date_str.starts_with('-') {
        // Negative year: '-0500-01-01' -> -500
        let rest = &date_str[1..]; // '0500-01-01'
        let year_str = rest.split('-').next()?;
        let year: i32 = year_str.parse().ok()?;
        Some(-(year as i32))
    } else {
        // Positive year: '1972-04-11' -> 1972
        let year_str = date_str.split('-').next()?;
        let year: i32 = year_str.parse().ok()?;
        Some(year)
    }
}

#[derive(Clone)]
struct RegionEntry {
    macro_region: String,
    region: String,
    start_year: i32,
    end_year: Option<i32>,
}

fn main() -> Result<()> {
    log("=== Step 29: Add regions to individuals_countries ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // Build region lookup: iso_a3 -> Vec<RegionEntry>
    log("[29] Building region lookup from regions table...");
    let mut region_lookup: HashMap<String, Vec<RegionEntry>> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT macro_region, region, iso_a3, start_year, end_year FROM regions",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, i32>(3)?,
                r.get::<_, Option<i32>>(4)?,
            ))
        })?;
        for r in rows {
            let (macro_region, region, iso_a3, start_year, end_year) = r?;
            region_lookup
                .entry(iso_a3)
                .or_default()
                .push(RegionEntry {
                    macro_region,
                    region,
                    start_year,
                    end_year,
                });
        }
    }
    log(&format!(
        "[29] Region lookup: {} country codes with region mappings",
        region_lookup.len()
    ));

    // Build impact_date lookup: wikidata_id -> year
    log("[29] Building impact_date lookup...");
    let mut impact_lookup: HashMap<String, i32> = HashMap::new();
    {
        let mut stmt =
            conn.prepare("SELECT wikidata_id, impact_date FROM individuals_impact_date")?;
        let rows = stmt.query_map([], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
        })?;
        for r in rows {
            let (wid, date_str) = r?;
            if let Some(year) = parse_year(&date_str) {
                impact_lookup.insert(wid, year);
            }
        }
    }
    log(&format!(
        "[29] Impact date lookup: {} entries",
        impact_lookup.len()
    ));

    // Add columns to individuals_countries if they don't exist
    log("[29] Adding region and macro_region columns...");
    // Check if columns already exist
    let col_exists: bool = {
        let mut stmt = conn.prepare("PRAGMA table_info(individuals_countries)")?;
        let cols: Vec<String> = stmt
            .query_map([], |r| r.get::<_, String>(1))?
            .filter_map(|r| r.ok())
            .collect();
        cols.contains(&"region".to_string())
    };

    if !col_exists {
        conn.execute_batch("ALTER TABLE individuals_countries ADD COLUMN region TEXT;")?;
        conn.execute_batch("ALTER TABLE individuals_countries ADD COLUMN macro_region TEXT;")?;
        log("[29] Added region and macro_region columns");
    } else {
        // Reset existing values
        conn.execute_batch("UPDATE individuals_countries SET region = NULL, macro_region = NULL;")?;
        log("[29] Reset existing region and macro_region columns");
    }

    // Process individuals_countries in batches
    let total: i64 = conn.query_row("SELECT COUNT(*) FROM individuals_countries", [], |r| {
        r.get(0)
    })?;
    log(&format!(
        "[29] Total rows in individuals_countries: {}",
        total
    ));

    let pb = ProgressBar::new(total as u64);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{msg} [{bar:40}] {pos}/{len} ({eta})")
            .unwrap(),
    );
    pb.set_message("Adding regions");

    let mut offset: i64 = 0;
    let mut matched_count = 0u64;
    let mut unmatched_count = 0u64;
    let mut no_impact_date = 0u64;

    loop {
        // Read a batch of individuals_countries
        let mut batch: Vec<(String, String)> = Vec::with_capacity(BATCH_SIZE);
        {
            let mut stmt = conn.prepare_cached(
                "SELECT wikidata_id, iso_a3_code FROM individuals_countries ORDER BY rowid LIMIT ?1 OFFSET ?2",
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
            let mut update_stmt = conn.prepare_cached(
                "UPDATE individuals_countries SET region = ?1, macro_region = ?2 WHERE wikidata_id = ?3",
            )?;

            for (wikidata_id, iso_a3) in &batch {
                // Get the impact year for this individual
                let impact_year = impact_lookup.get(wikidata_id.as_str());

                if let Some(&year) = impact_year {
                    // Find all matching regions for this country + year
                    if let Some(entries) = region_lookup.get(iso_a3.as_str()) {
                        let mut regions: Vec<&str> = Vec::new();
                        let mut macro_regions: Vec<&str> = Vec::new();

                        for entry in entries {
                            let in_range = year >= entry.start_year
                                && match entry.end_year {
                                    Some(end) => year <= end,
                                    None => true,
                                };

                            if in_range {
                                if !regions.contains(&entry.region.as_str()) {
                                    regions.push(&entry.region);
                                }
                                if !macro_regions.contains(&entry.macro_region.as_str()) {
                                    macro_regions.push(&entry.macro_region);
                                }
                            }
                        }

                        if !regions.is_empty() {
                            let region_str = regions.join("; ");
                            let macro_str = macro_regions.join("; ");
                            update_stmt.execute(params![region_str, macro_str, wikidata_id])?;
                            matched_count += 1;
                        } else {
                            unmatched_count += 1;
                        }
                    } else {
                        unmatched_count += 1;
                    }
                } else {
                    no_impact_date += 1;
                }
            }
        }
        conn.execute_batch("COMMIT;")?;

        pb.inc(batch.len() as u64);
        offset += batch.len() as i64;

        // Log progress every 500k
        if offset % 500_000 < BATCH_SIZE as i64 {
            log(&format!(
                "[29] Progress: {}/{} processed, {} matched, {} unmatched, {} no impact date",
                offset, total, matched_count, unmatched_count, no_impact_date
            ));
        }
    }
    pb.finish();

    // Create indexes
    log("[29] Creating indexes...");
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_indcountries_region ON individuals_countries(region);",
    )?;
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_indcountries_macro_region ON individuals_countries(macro_region);",
    )?;

    // Final statistics
    let with_region: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals_countries WHERE region IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    let without_region: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals_countries WHERE region IS NULL",
        [],
        |r| r.get(0),
    )?;

    log(&format!("[29] === Final Statistics ==="));
    log(&format!("[29] Total rows: {}", total));
    log(&format!("[29] With region: {}", with_region));
    log(&format!("[29] Without region: {}", without_region));
    log(&format!("[29] Matched: {}", matched_count));
    log(&format!("[29] Unmatched (no region for country): {}", unmatched_count));
    log(&format!("[29] No impact date: {}", no_impact_date));

    // Show top regions
    let mut stmt = conn.prepare(
        "SELECT region, COUNT(*) as cnt FROM individuals_countries WHERE region IS NOT NULL GROUP BY region ORDER BY cnt DESC LIMIT 20",
    )?;
    let rows: Vec<(String, i64)> = stmt
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[29] Top 20 regions:");
    for (reg, cnt) in &rows {
        log(&format!("[29]   {} -> {}", reg, cnt));
    }

    // Show top macro_regions
    let mut stmt = conn.prepare(
        "SELECT macro_region, COUNT(*) as cnt FROM individuals_countries WHERE macro_region IS NOT NULL GROUP BY macro_region ORDER BY cnt DESC LIMIT 10",
    )?;
    let rows: Vec<(String, i64)> = stmt
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[29] Top macro_regions:");
    for (mr, cnt) in &rows {
        log(&format!("[29]   {} -> {}", mr, cnt));
    }

    log("=== Step 29 complete ===");
    Ok(())
}
