/// Step 25: Recover iso_country for NULL-coord cities + rebuild individuals_countries
///
/// For cities where iso_country_name IS NULL, if original_country_name matches
/// a modern_country.name exactly, fill in iso_country_name and iso_a3_code.
/// Then rebuild individuals_countries with updated data.
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

fn main() -> Result<()> {
    log("=== Step 25: Recover iso_country for NULL-coord cities + rebuild individuals_countries ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // ==========================================
    // 1. Fill in iso_country from original_country_name matching modern_country
    // ==========================================
    let null_before: i64 = conn.query_row(
        "SELECT COUNT(*) FROM cities WHERE iso_country_name IS NULL",
        [],
        |r| r.get(0),
    )?;
    log(&format!("[25] Cities with NULL iso_country_name: {}", null_before));

    let updated = conn.execute(
        "UPDATE cities
         SET iso_country_name = (SELECT mc.name FROM modern_country mc WHERE mc.name = cities.original_country_name LIMIT 1),
             iso_a3_code = (SELECT mc.iso_a3_code FROM modern_country mc WHERE mc.name = cities.original_country_name LIMIT 1)
         WHERE iso_country_name IS NULL
           AND original_country_name IS NOT NULL
           AND EXISTS (SELECT 1 FROM modern_country mc WHERE mc.name = cities.original_country_name)",
        [],
    )?;
    log(&format!("[25] Recovered iso_country for {} cities", updated));

    let null_after: i64 = conn.query_row(
        "SELECT COUNT(*) FROM cities WHERE iso_country_name IS NULL",
        [],
        |r| r.get(0),
    )?;
    log(&format!("[25] Cities still with NULL iso_country_name: {}", null_after));

    // Show some recovered examples
    let mut sample = conn.prepare(
        "SELECT id, name_en, original_country_name, iso_country_name, iso_a3_code
         FROM cities WHERE lat IS NULL AND lon IS NULL AND iso_country_name IS NOT NULL LIMIT 5",
    )?;
    let rows: Vec<(String, Option<String>, Option<String>, Option<String>, Option<String>)> = sample
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[25] Sample recovered cities:");
    for (id, name, orig, iso_cn, iso) in &rows {
        log(&format!(
            "[25]   {} ({}) orig={} -> iso={} ({})",
            id,
            name.as_deref().unwrap_or("?"),
            orig.as_deref().unwrap_or("?"),
            iso_cn.as_deref().unwrap_or("?"),
            iso.as_deref().unwrap_or("?")
        ));
    }

    // ==========================================
    // 2. Rebuild individuals_countries
    // ==========================================
    log("[25] Rebuilding individuals_countries...");

    let mut nat_lookup: HashMap<String, (String, String)> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT name_en, iso_country_name, iso_a3_code FROM nationalities WHERE iso_country_name IS NOT NULL AND iso_a3_code IS NOT NULL",
        )?;
        for r in stmt.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?)))? {
            let (name, country, iso) = r?;
            nat_lookup.insert(name, (country, iso));
        }
    }
    log(&format!("[25] Nationality lookup: {} entries", nat_lookup.len()));

    let mut city_lookup: HashMap<String, (String, String)> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT name_en, iso_country_name, iso_a3_code FROM cities WHERE iso_country_name IS NOT NULL AND iso_a3_code IS NOT NULL",
        )?;
        for r in stmt.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?)))? {
            let (name, country, iso) = r?;
            city_lookup.entry(name).or_insert((country, iso));
        }
    }
    log(&format!("[25] City lookup: {} entries", city_lookup.len()));

    conn.execute_batch("DROP TABLE IF EXISTS individuals_countries;")?;
    conn.execute_batch(
        "CREATE TABLE individuals_countries (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            iso_country_name TEXT NOT NULL,
            iso_a3_code TEXT NOT NULL,
            origins TEXT NOT NULL
        );",
    )?;

    let total: i64 = conn.query_row("SELECT COUNT(*) FROM individuals", [], |r| r.get(0))?;
    log(&format!("[25] Total individuals: {}", total));

    let pb = ProgressBar::new(total as u64);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{msg} [{bar:40}] {pos}/{len} ({eta})")
            .unwrap(),
    );
    pb.set_message("Processing individuals");

    let mut offset: i64 = 0;
    let mut matched_nat = 0u64;
    let mut matched_death = 0u64;
    let mut matched_birth = 0u64;
    let mut unmatched = 0u64;
    let mut total_inserted = 0u64;

    loop {
        let mut batch: Vec<(String, Option<String>, Option<String>, Option<String>, Option<String>)> =
            Vec::with_capacity(BATCH_SIZE);
        {
            let mut stmt = conn.prepare_cached(
                "SELECT wikidata_id, name_en, nationalities_en, deathcity_en, birthcity_en
                 FROM individuals ORDER BY rowid LIMIT ?1 OFFSET ?2",
            )?;
            for r in stmt.query_map(params![BATCH_SIZE as i64, offset], |r| {
                Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?))
            })? {
                batch.push(r?);
            }
        }

        if batch.is_empty() { break; }

        conn.execute_batch("BEGIN TRANSACTION;")?;
        {
            let mut ins = conn.prepare_cached(
                "INSERT OR IGNORE INTO individuals_countries (wikidata_id, name_en, iso_country_name, iso_a3_code, origins)
                 VALUES (?1, ?2, ?3, ?4, ?5)",
            )?;

            for (wid, name, nats, death, birth) in &batch {
                let mut found = false;

                if let Some(nats) = nats {
                    for n in nats.split("; ") {
                        if let Some((c, i)) = nat_lookup.get(n.trim()) {
                            ins.execute(params![wid, name, c, i, "nationality"])?;
                            matched_nat += 1;
                            total_inserted += 1;
                            found = true;
                            break;
                        }
                    }
                }
                if found { continue; }

                if let Some(city) = death {
                    if let Some((c, i)) = city_lookup.get(city.trim()) {
                        ins.execute(params![wid, name, c, i, "deathplace"])?;
                        matched_death += 1;
                        total_inserted += 1;
                        found = true;
                    }
                }
                if found { continue; }

                if let Some(city) = birth {
                    if let Some((c, i)) = city_lookup.get(city.trim()) {
                        ins.execute(params![wid, name, c, i, "birthplace"])?;
                        matched_birth += 1;
                        total_inserted += 1;
                        found = true;
                    }
                }
                if !found { unmatched += 1; }
            }
        }
        conn.execute_batch("COMMIT;")?;

        pb.inc(batch.len() as u64);
        offset += batch.len() as i64;

        if offset % 500_000 < BATCH_SIZE as i64 {
            log(&format!(
                "[25] Progress: {}/{} | inserted: {} (nat:{}, death:{}, birth:{}) | unmatched: {}",
                offset, total, total_inserted, matched_nat, matched_death, matched_birth, unmatched
            ));
        }
    }
    pb.finish();

    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_indcountries_iso_country ON individuals_countries(iso_country_name);
         CREATE INDEX IF NOT EXISTS idx_indcountries_iso ON individuals_countries(iso_a3_code);
         CREATE INDEX IF NOT EXISTS idx_indcountries_origins ON individuals_countries(origins);",
    )?;

    let final_count: i64 = conn.query_row("SELECT COUNT(*) FROM individuals_countries", [], |r| r.get(0))?;

    log("[25] === Final Statistics ===");
    log(&format!("[25] Total matched: {} (prev: 6,372,267, diff: {:+})", final_count, final_count - 6_372_267));
    log(&format!("[25]   nationality: {}", matched_nat));
    log(&format!("[25]   deathplace: {}", matched_death));
    log(&format!("[25]   birthplace: {}", matched_birth));
    log(&format!("[25] Unmatched: {}", unmatched));

    let mut top = conn.prepare(
        "SELECT iso_country_name, iso_a3_code, COUNT(*) FROM individuals_countries GROUP BY iso_country_name ORDER BY COUNT(*) DESC LIMIT 15",
    )?;
    let rows: Vec<(String, String, i64)> = top
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[25] Top 15:");
    for (n, i, c) in &rows { log(&format!("[25]   {} ({}) -> {}", n, i, c)); }

    log("=== Step 25 complete ===");
    Ok(())
}
