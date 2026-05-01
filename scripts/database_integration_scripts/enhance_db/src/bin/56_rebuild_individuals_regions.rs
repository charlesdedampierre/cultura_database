/// Rebuild individuals_regions from the updated individuals_countries
/// (which now includes impact_year) + regions table.
///
/// Same logic as step 52, but reads impact_year directly from
/// individuals_countries instead of looking it up separately from
/// individuals_impact_date.
///
/// Associates each individual with a region and macro_region based on:
/// 1. Their country from individuals_countries (iso_a3_code)
/// 2. Their impact_year from individuals_countries
/// 3. The regions table (iso_a3 + start_year/end_year range)
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

#[derive(Clone)]
struct RegionEntry {
    macro_region: String,
    region: String,
    start_year: i32,
    end_year: Option<i32>,
}

fn main() -> Result<()> {
    let _ = fs::remove_file(TASK_LOG);
    log("=== Step 56: Rebuild individuals_regions (impact_year from individuals_countries) ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // ========================================================
    // PHASE 1: Build region lookup
    // ========================================================

    log("[56] Building region lookup from regions table...");
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
        "[56] Region lookup: {} country codes with region mappings",
        region_lookup.len()
    ));

    // ========================================================
    // PHASE 2: Drop and recreate individuals_regions table
    // ========================================================
    log("[56] Creating fresh individuals_regions table...");
    conn.execute_batch("DROP TABLE IF EXISTS individuals_regions;")?;
    conn.execute_batch(
        "CREATE TABLE individuals_regions (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            iso_country_name TEXT,
            iso_a3_code TEXT,
            origins TEXT,
            region TEXT,
            macro_region TEXT,
            impact_year INTEGER
        );",
    )?;
    log("[56] Created fresh individuals_regions table");

    // ========================================================
    // PHASE 3: Populate from individuals_countries (which now has impact_year)
    // ========================================================
    let total: i64 =
        conn.query_row("SELECT COUNT(*) FROM individuals_countries", [], |r| {
            r.get(0)
        })?;
    log(&format!(
        "[56] Total rows in individuals_countries to process: {}",
        total
    ));

    let pb = ProgressBar::new(total as u64);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{msg} [{bar:40}] {pos}/{len} ({eta})")
            .unwrap(),
    );
    pb.set_message("Creating individuals_regions");

    let mut offset: i64 = 0;
    let mut matched_count = 0u64;
    let mut unmatched_no_region = 0u64;
    let mut no_impact_year = 0u64;
    let mut total_inserted = 0u64;

    loop {
        let mut batch: Vec<(String, Option<String>, Option<String>, String, Option<String>, Option<i32>)> =
            Vec::with_capacity(BATCH_SIZE);
        {
            let mut stmt = conn.prepare_cached(
                "SELECT wikidata_id, name_en, iso_country_name, iso_a3_code, origins, impact_year
                 FROM individuals_countries
                 ORDER BY rowid
                 LIMIT ?1 OFFSET ?2",
            )?;
            let rows = stmt.query_map(params![BATCH_SIZE as i64, offset], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, Option<String>>(1)?,
                    r.get::<_, Option<String>>(2)?,
                    r.get::<_, String>(3)?,
                    r.get::<_, Option<String>>(4)?,
                    r.get::<_, Option<i32>>(5)?,
                ))
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
            let mut insert = conn.prepare_cached(
                "INSERT OR IGNORE INTO individuals_regions
                 (wikidata_id, name_en, iso_country_name, iso_a3_code, origins, region, macro_region, impact_year)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
            )?;

            for (wikidata_id, name_en, iso_country_name, iso_a3, origins, impact_year) in &batch {
                if let Some(year) = impact_year {
                    if let Some(entries) = region_lookup.get(iso_a3.as_str()) {
                        let mut regions: Vec<&str> = Vec::new();
                        let mut macro_regions: Vec<&str> = Vec::new();

                        for entry in entries {
                            let in_range = *year >= entry.start_year
                                && match entry.end_year {
                                    Some(end) => *year <= end,
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
                            insert.execute(params![
                                wikidata_id,
                                name_en,
                                iso_country_name,
                                iso_a3,
                                origins,
                                region_str,
                                macro_str,
                                year,
                            ])?;
                            matched_count += 1;
                            total_inserted += 1;
                        } else {
                            unmatched_no_region += 1;
                        }
                    } else {
                        unmatched_no_region += 1;
                    }
                } else {
                    no_impact_year += 1;
                }
            }
        }
        conn.execute_batch("COMMIT;")?;

        pb.inc(batch.len() as u64);
        offset += batch.len() as i64;

        if offset % 500_000 < BATCH_SIZE as i64 {
            log(&format!(
                "[56] Progress: {}/{} processed, {} inserted, {} no region match, {} no impact year",
                offset, total, total_inserted, unmatched_no_region, no_impact_year
            ));
        }
    }
    pb.finish();

    // ========================================================
    // PHASE 4: Create indexes
    // ========================================================
    log("[56] Creating indexes...");
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_indregions_region ON individuals_regions(region);",
    )?;
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_indregions_macro_region ON individuals_regions(macro_region);",
    )?;
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_indregions_iso ON individuals_regions(iso_a3_code);",
    )?;
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_indregions_country ON individuals_regions(iso_country_name);",
    )?;
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_indregions_year ON individuals_regions(impact_year);",
    )?;

    // ========================================================
    // PHASE 5: Final statistics
    // ========================================================
    let final_count: i64 =
        conn.query_row("SELECT COUNT(*) FROM individuals_regions", [], |r| {
            r.get(0)
        })?;
    let with_region: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals_regions WHERE region IS NOT NULL",
        [],
        |r| r.get(0),
    )?;

    log("[56] === Final Statistics ===");
    log(&format!("[56] Total individuals_countries: {}", total));
    log(&format!("[56] Total in individuals_regions: {}", final_count));
    log(&format!("[56] With region assigned: {}", with_region));
    log(&format!("[56] Matched to region: {}", matched_count));
    log(&format!(
        "[56] No region match (country not in regions table): {}",
        unmatched_no_region
    ));
    log(&format!("[56] No impact year available: {}", no_impact_year));

    // Top 20 regions
    let mut stmt = conn.prepare(
        "SELECT region, COUNT(*) as cnt FROM individuals_regions WHERE region IS NOT NULL GROUP BY region ORDER BY cnt DESC LIMIT 20",
    )?;
    let rows: Vec<(String, i64)> = stmt
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[56] Top 20 regions:");
    for (reg, cnt) in &rows {
        log(&format!("[56]   {} -> {}", reg, cnt));
    }

    // Top macro_regions
    let mut stmt = conn.prepare(
        "SELECT macro_region, COUNT(*) as cnt FROM individuals_regions WHERE macro_region IS NOT NULL GROUP BY macro_region ORDER BY cnt DESC",
    )?;
    let rows: Vec<(String, i64)> = stmt
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[56] Macro regions:");
    for (mr, cnt) in &rows {
        log(&format!("[56]   {} -> {}", mr, cnt));
    }

    log("=== Step 56 complete ===");
    Ok(())
}
