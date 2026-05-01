/// Step 26: Fill in iso_country for nationalities using QLEVER-extracted parent country data.
/// Then rebuild individuals_countries.
use anyhow::Result;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection};
use serde_json::Value;
use std::collections::HashMap;
use std::fs;
use std::io::Write;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const PARENT_COUNTRIES_PATH: &str = "data/all_humans/nationality_parent_countries.json";
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
    log("=== Step 26: Fill nationality countries from QLEVER data + rebuild individuals_countries ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // Load parent country mappings
    log("[26] Loading parent country mappings...");
    let raw = fs::read_to_string(PARENT_COUNTRIES_PATH)?;
    let parent_countries: HashMap<String, Value> = serde_json::from_str(&raw)?;
    log(&format!("[26] Loaded {} mappings", parent_countries.len()));

    // Update nationalities
    let null_before: i64 = conn.query_row(
        "SELECT COUNT(*) FROM nationalities WHERE iso_country_name IS NULL",
        [],
        |r| r.get(0),
    )?;
    log(&format!("[26] Nationalities without iso_country: {}", null_before));

    let mut updated = 0;
    {
        let mut update_stmt = conn.prepare(
            "UPDATE nationalities SET iso_country_name = ?1, iso_a3_code = ?2 WHERE wikidata_id = ?3 AND iso_country_name IS NULL",
        )?;

        for (qid, val) in &parent_countries {
            let country_name = val.get("country_name").and_then(|v| v.as_str());
            let iso_a3 = val.get("iso_a3_code").and_then(|v| v.as_str());
            if let (Some(cn), Some(iso)) = (country_name, iso_a3) {
                let rows = update_stmt.execute(params![cn, iso, qid])?;
                if rows > 0 {
                    updated += 1;
                }
            }
        }
    }

    let null_after: i64 = conn.query_row(
        "SELECT COUNT(*) FROM nationalities WHERE iso_country_name IS NULL",
        [],
        |r| r.get(0),
    )?;
    log(&format!(
        "[26] Updated {} nationalities. Still NULL: {} (was {})",
        updated, null_after, null_before
    ));

    // Show top updated
    let mut sample = conn.prepare(
        "SELECT wikidata_id, name_en, count, iso_country_name, iso_a3_code
         FROM nationalities WHERE iso_country_name IS NOT NULL ORDER BY count DESC LIMIT 5",
    )?;
    let rows: Vec<(String, Option<String>, i64, Option<String>, Option<String>)> = sample
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[26] Top nationalities with iso_country:");
    for (qid, name, cnt, cn, iso) in &rows {
        log(&format!(
            "[26]   {} ({}, count={}) -> {} ({})",
            qid,
            name.as_deref().unwrap_or("?"),
            cnt,
            cn.as_deref().unwrap_or("?"),
            iso.as_deref().unwrap_or("?")
        ));
    }

    // Rebuild individuals_countries
    log("[26] Rebuilding individuals_countries...");

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
    log(&format!("[26] Nationality lookup: {} entries (was 2828)", nat_lookup.len()));

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
    log(&format!("[26] City lookup: {} entries", city_lookup.len()));

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
    log(&format!("[26] Total individuals: {}", total));

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
                "[26] Progress: {}/{} | inserted: {} (nat:{}, death:{}, birth:{}) | unmatched: {}",
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

    log("[26] === Final Statistics ===");
    log(&format!("[26] Total matched: {} (prev: 6,373,209, diff: {:+})", final_count, final_count - 6_373_209));
    log(&format!("[26]   nationality: {}", matched_nat));
    log(&format!("[26]   deathplace: {}", matched_death));
    log(&format!("[26]   birthplace: {}", matched_birth));
    log(&format!("[26] Unmatched: {}", unmatched));

    let mut top = conn.prepare(
        "SELECT iso_country_name, iso_a3_code, COUNT(*) FROM individuals_countries GROUP BY iso_country_name ORDER BY COUNT(*) DESC LIMIT 15",
    )?;
    let rows: Vec<(String, String, i64)> = top
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[26] Top 15:");
    for (n, i, c) in &rows { log(&format!("[26]   {} ({}) -> {}", n, i, c)); }

    log("=== Step 26 complete ===");
    Ok(())
}
