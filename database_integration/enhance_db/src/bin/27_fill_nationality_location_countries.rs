/// Step 27: Add iso_modern_country_origin column, fill nationality countries from location-based
/// extraction, and rebuild individuals_countries.
use anyhow::Result;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection};
use serde_json::Value;
use std::collections::HashMap;
use std::fs;
use std::io::Write;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const LOCATION_COUNTRIES_PATH: &str = "data/all_humans/nationality_location_countries.json";
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
    log("=== Step 27: Add iso_modern_country_origin + fill nationality location countries + rebuild individuals_countries ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // ============================================
    // Part 1: Add iso_modern_country_origin column
    // ============================================
    log("[27] Part 1: Adding iso_modern_country_origin column...");

    // Check if column already exists
    let has_origin_col: bool = {
        let mut stmt = conn.prepare("PRAGMA table_info(nationalities)")?;
        let cols: Vec<String> = stmt
            .query_map([], |r| r.get::<_, String>(1))?
            .filter_map(|r| r.ok())
            .collect();
        cols.contains(&"iso_modern_country_origin".to_string())
    };

    if !has_origin_col {
        conn.execute_batch(
            "ALTER TABLE nationalities ADD COLUMN iso_modern_country_origin TEXT;",
        )?;
        log("[27] Column iso_modern_country_origin added.");
    } else {
        log("[27] Column iso_modern_country_origin already exists.");
    }

    // ============================================
    // Part 2: Set origin for existing mapped entries
    // ============================================
    log("[27] Part 2: Setting origin for already-mapped nationalities...");

    // Set "reverse_geocode" for entries with lat/lon
    let reverse_geocode_count: usize = conn.execute(
        "UPDATE nationalities SET iso_modern_country_origin = 'reverse_geocode'
         WHERE iso_country_name IS NOT NULL AND lat IS NOT NULL AND lon IS NOT NULL
         AND iso_modern_country_origin IS NULL",
        [],
    )?;
    log(&format!(
        "[27] Set 'reverse_geocode' for {} entries (had lat/lon)",
        reverse_geocode_count
    ));

    // For the ~243 entries without lat/lon but with iso_country_name,
    // look up their source from nationality_parent_countries.json
    let parent_origins: HashMap<String, String> = if let Ok(raw) =
        fs::read_to_string(PARENT_COUNTRIES_PATH)
    {
        let parent_data: HashMap<String, Value> = serde_json::from_str(&raw)?;
        parent_data
            .iter()
            .filter_map(|(qid, val)| {
                let source = val.get("source").and_then(|v| v.as_str()).unwrap_or("qlever_relation");
                // Normalize old source names
                let normalized = match source {
                    "relation" => "qlever_relation",
                    "relation_id" => "qlever_relation",
                    "2hop_relation" => "qlever_2hop_relation",
                    "successor" => "qlever_replaced_by",
                    "3hop" => "qlever_3hop_relation",
                    "coordinates" => "reverse_geocode",
                    other => other,
                };
                Some((qid.clone(), normalized.to_string()))
            })
            .collect()
    } else {
        log("[27] Warning: Could not read parent_countries file, skipping origin backfill for those.");
        HashMap::new()
    };

    // Update the ones without lat/lon
    {
        let mut update_stmt = conn.prepare(
            "UPDATE nationalities SET iso_modern_country_origin = ?1
             WHERE wikidata_id = ?2 AND iso_country_name IS NOT NULL AND iso_modern_country_origin IS NULL",
        )?;

        let mut parent_updated = 0;
        for (qid, origin) in &parent_origins {
            let rows = update_stmt.execute(params![origin, qid])?;
            if rows > 0 {
                parent_updated += 1;
            }
        }
        log(&format!(
            "[27] Set origin from parent_countries for {} entries",
            parent_updated
        ));
    }

    // Any remaining mapped but without origin → mark as "unknown_legacy"
    let legacy_count: usize = conn.execute(
        "UPDATE nationalities SET iso_modern_country_origin = 'unknown_legacy'
         WHERE iso_country_name IS NOT NULL AND iso_modern_country_origin IS NULL",
        [],
    )?;
    if legacy_count > 0 {
        log(&format!(
            "[27] Set 'unknown_legacy' for {} remaining mapped entries",
            legacy_count
        ));
    }

    // ============================================
    // Part 3: Apply new location-based mappings
    // ============================================
    log("[27] Part 3: Applying new location-based mappings...");

    let raw = fs::read_to_string(LOCATION_COUNTRIES_PATH)?;
    let location_countries: HashMap<String, Value> = serde_json::from_str(&raw)?;
    log(&format!("[27] Loaded {} new mappings", location_countries.len()));

    let null_before: i64 = conn.query_row(
        "SELECT COUNT(*) FROM nationalities WHERE iso_country_name IS NULL",
        [],
        |r| r.get(0),
    )?;
    log(&format!(
        "[27] Nationalities without iso_country: {} (before)",
        null_before
    ));

    let mut updated = 0;
    {
        let mut update_stmt = conn.prepare(
            "UPDATE nationalities SET iso_country_name = ?1, iso_a3_code = ?2, iso_modern_country_origin = ?3
             WHERE wikidata_id = ?4 AND iso_country_name IS NULL",
        )?;

        for (qid, val) in &location_countries {
            let country_name = val.get("country_name").and_then(|v| v.as_str());
            let iso_a3 = val.get("iso_a3_code").and_then(|v| v.as_str());
            let source = val.get("source").and_then(|v| v.as_str()).unwrap_or("unknown");

            if let (Some(cn), Some(iso)) = (country_name, iso_a3) {
                let rows = update_stmt.execute(params![cn, iso, source, qid])?;
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
        "[27] Updated {} nationalities. Still NULL: {} (was {})",
        updated, null_after, null_before
    ));

    // Show origin breakdown
    {
        let mut stmt = conn.prepare(
            "SELECT iso_modern_country_origin, COUNT(*) FROM nationalities
             GROUP BY iso_modern_country_origin ORDER BY COUNT(*) DESC",
        )?;
        let rows: Vec<(Option<String>, i64)> = stmt
            .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
            .filter_map(|r| r.ok())
            .collect();
        log("[27] Origin breakdown:");
        for (origin, count) in &rows {
            log(&format!(
                "[27]   {}: {}",
                origin.as_deref().unwrap_or("NULL"),
                count
            ));
        }
    }

    // Show top updated
    {
        let mut sample = conn.prepare(
            "SELECT wikidata_id, name_en, count, iso_country_name, iso_a3_code, iso_modern_country_origin
             FROM nationalities WHERE iso_modern_country_origin NOT IN ('reverse_geocode', 'unknown_legacy')
             AND iso_country_name IS NOT NULL ORDER BY count DESC LIMIT 15",
        )?;
        let rows: Vec<(String, Option<String>, i64, Option<String>, Option<String>, Option<String>)> = sample
            .query_map([], |r| {
                Ok((
                    r.get(0)?,
                    r.get(1)?,
                    r.get(2)?,
                    r.get(3)?,
                    r.get(4)?,
                    r.get(5)?,
                ))
            })?
            .filter_map(|r| r.ok())
            .collect();
        log("[27] Top recently mapped nationalities:");
        for (qid, name, cnt, cn, iso, origin) in &rows {
            log(&format!(
                "[27]   {} ({}, cnt={}) -> {} ({}) [{}]",
                qid,
                name.as_deref().unwrap_or("?"),
                cnt,
                cn.as_deref().unwrap_or("?"),
                iso.as_deref().unwrap_or("?"),
                origin.as_deref().unwrap_or("?")
            ));
        }
    }

    // ============================================
    // Part 4: Rebuild individuals_countries
    // ============================================
    log("[27] Part 4: Rebuilding individuals_countries...");

    let mut nat_lookup: HashMap<String, (String, String)> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT name_en, iso_country_name, iso_a3_code FROM nationalities
             WHERE iso_country_name IS NOT NULL AND iso_a3_code IS NOT NULL",
        )?;
        for r in stmt.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
            ))
        })? {
            let (name, country, iso) = r?;
            nat_lookup.insert(name, (country, iso));
        }
    }
    log(&format!("[27] Nationality lookup: {} entries", nat_lookup.len()));

    let mut city_lookup: HashMap<String, (String, String)> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT name_en, iso_country_name, iso_a3_code FROM cities
             WHERE iso_country_name IS NOT NULL AND iso_a3_code IS NOT NULL",
        )?;
        for r in stmt.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
            ))
        })? {
            let (name, country, iso) = r?;
            city_lookup.entry(name).or_insert((country, iso));
        }
    }
    log(&format!("[27] City lookup: {} entries", city_lookup.len()));

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
    log(&format!("[27] Total individuals: {}", total));

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
        let mut batch: Vec<(
            String,
            Option<String>,
            Option<String>,
            Option<String>,
            Option<String>,
        )> = Vec::with_capacity(BATCH_SIZE);
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

        if batch.is_empty() {
            break;
        }

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
                if found {
                    continue;
                }

                if let Some(city) = death {
                    if let Some((c, i)) = city_lookup.get(city.trim()) {
                        ins.execute(params![wid, name, c, i, "deathplace"])?;
                        matched_death += 1;
                        total_inserted += 1;
                        found = true;
                    }
                }
                if found {
                    continue;
                }

                if let Some(city) = birth {
                    if let Some((c, i)) = city_lookup.get(city.trim()) {
                        ins.execute(params![wid, name, c, i, "birthplace"])?;
                        matched_birth += 1;
                        total_inserted += 1;
                        found = true;
                    }
                }
                if !found {
                    unmatched += 1;
                }
            }
        }
        conn.execute_batch("COMMIT;")?;

        pb.inc(batch.len() as u64);
        offset += batch.len() as i64;

        if offset % 500_000 < BATCH_SIZE as i64 {
            log(&format!(
                "[27] Progress: {}/{} | inserted: {} (nat:{}, death:{}, birth:{}) | unmatched: {}",
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

    let final_count: i64 =
        conn.query_row("SELECT COUNT(*) FROM individuals_countries", [], |r| r.get(0))?;

    log("[27] === Final Statistics ===");
    log(&format!("[27] Total matched: {}", final_count));
    log(&format!("[27]   nationality: {}", matched_nat));
    log(&format!("[27]   deathplace: {}", matched_death));
    log(&format!("[27]   birthplace: {}", matched_birth));
    log(&format!("[27] Unmatched: {}", unmatched));

    let mut top = conn.prepare(
        "SELECT iso_country_name, iso_a3_code, COUNT(*) FROM individuals_countries
         GROUP BY iso_country_name ORDER BY COUNT(*) DESC LIMIT 15",
    )?;
    let rows: Vec<(String, String, i64)> = top
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[27] Top 15 countries:");
    for (n, i, c) in &rows {
        log(&format!("[27]   {} ({}) -> {}", n, i, c));
    }

    log("=== Step 27 complete ===");
    Ok(())
}
