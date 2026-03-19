/// Create a `consolidate` table that brings together key data for each individual
/// who belongs to at least one Cliopatria polity.
///
/// Columns:
///   wikidata_id, name_en, impact_year, polity_name, occupations (;-separated),
///   gender, references_count, is_scientist (0/1), is_artist (0/1)
///
/// Phase 1: Build occupation_id -> meta_occupation lookup
/// Phase 2: Bulk INSERT from individuals_cliopatria JOIN individuals
/// Phase 3: Update is_scientist / is_artist from individuals_keys + occupations lookup
/// Phase 4: Create indexes
/// Phase 5: Export to CSV
/// Phase 6: Statistics
use anyhow::Result;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection};
use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::time::Instant;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const CSV_PATH: &str = "data/consolidate.csv";
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

fn elapsed(start: Instant) -> String {
    let s = start.elapsed().as_secs();
    if s < 60 {
        format!("{}s", s)
    } else if s < 3600 {
        format!("{}m {}s", s / 60, s % 60)
    } else {
        format!("{}h {}m {}s", s / 3600, (s % 3600) / 60, s % 60)
    }
}

/// Escape a field for CSV output (RFC 4180)
fn csv_escape(field: &str) -> String {
    if field.contains(',') || field.contains('"') || field.contains('\n') || field.contains('\r') {
        format!("\"{}\"", field.replace('"', "\"\""))
    } else {
        field.to_string()
    }
}

fn main() -> Result<()> {
    let _ = fs::remove_file(TASK_LOG);
    let total_start = Instant::now();
    log("=== Step 45: Create consolidate table ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // ========================================================
    // PHASE 1: Build occupation_id -> meta_occupation lookup
    // ========================================================
    log("[45] Phase 1: Building occupation lookup...");
    let mut occ_lookup: HashMap<String, String> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT id, meta_occupation FROM occupations WHERE meta_occupation IS NOT NULL",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
        })?;
        for r in rows {
            let (id, meta) = r?;
            occ_lookup.insert(id, meta);
        }
    }
    log(&format!(
        "[45] Occupation lookup: {} entries",
        occ_lookup.len()
    ));

    // ========================================================
    // PHASE 2: Create and populate consolidate table (bulk INSERT)
    // ========================================================
    log("[45] Phase 2: Creating and populating consolidate table...");
    let phase2_start = Instant::now();

    conn.execute_batch("DROP TABLE IF EXISTS consolidate;")?;
    conn.execute_batch(
        "CREATE TABLE consolidate (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            impact_year INTEGER,
            polity_name TEXT,
            occupations TEXT,
            gender TEXT,
            references_count INTEGER,
            is_scientist INTEGER DEFAULT 0,
            is_artist INTEGER DEFAULT 0
        );",
    )?;
    log("[45] Table created, now bulk inserting...");

    // Bulk insert using JOIN — only individuals that belong to at least one polity
    let inserted = conn.execute(
        "INSERT INTO consolidate (wikidata_id, name_en, impact_year, polity_name, occupations, gender, references_count)
         SELECT
             ic.wikidata_id,
             ic.name_en,
             ic.impact_date,
             ic.polity_name,
             i.occupations_en,
             i.gender,
             i.identifiers_count
         FROM individuals_cliopatria ic
         JOIN individuals i ON ic.wikidata_id = i.wikidata_id",
        [],
    )?;
    log(&format!(
        "[45] Phase 2: Inserted {} rows ({})",
        inserted,
        elapsed(phase2_start)
    ));

    // ========================================================
    // PHASE 3: Update is_scientist / is_artist flags
    // ========================================================
    let total: i64 = conn.query_row("SELECT COUNT(*) FROM consolidate", [], |r| r.get(0))?;
    log(&format!(
        "[45] Phase 3: Updating is_scientist/is_artist for {} rows...",
        total
    ));

    let pb = ProgressBar::new(total as u64);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{msg} [{bar:40}] {pos}/{len} ({eta})")
            .unwrap(),
    );
    pb.set_message("Updating scientist/artist flags");

    let mut offset: i64 = 0;
    let mut scientist_count = 0u64;
    let mut artist_count = 0u64;
    let mut updated_count = 0u64;

    loop {
        // Read batch of wikidata_ids from consolidate
        let mut batch: Vec<String> = Vec::with_capacity(BATCH_SIZE);
        {
            let mut stmt = conn.prepare_cached(
                "SELECT wikidata_id FROM consolidate ORDER BY rowid LIMIT ?1 OFFSET ?2",
            )?;
            let rows = stmt.query_map(params![BATCH_SIZE as i64, offset], |r| {
                r.get::<_, String>(0)
            })?;
            for r in rows {
                batch.push(r?);
            }
        }

        if batch.is_empty() {
            break;
        }

        // For each wikidata_id, look up occupations_ids and compute flags
        let mut updates: Vec<(String, i32, i32)> = Vec::new();
        for wid in &batch {
            let occ_ids: Option<String> = {
                let mut stmt = conn.prepare_cached(
                    "SELECT occupations_ids FROM individuals_keys WHERE wikidata_id = ?1",
                )?;
                stmt.query_row(params![wid], |r| r.get::<_, Option<String>>(0))
                    .unwrap_or(None)
            };

            if let Some(occ_ids_str) = occ_ids {
                let mut is_sci = 0i32;
                let mut is_art = 0i32;
                for occ_id in occ_ids_str.split(';') {
                    let occ_id = occ_id.trim();
                    if let Some(meta) = occ_lookup.get(occ_id) {
                        match meta.as_str() {
                            "scientist" => is_sci = 1,
                            "artist" => is_art = 1,
                            _ => {}
                        }
                    }
                    if is_sci == 1 && is_art == 1 {
                        break;
                    }
                }
                if is_sci == 1 || is_art == 1 {
                    updates.push((wid.clone(), is_sci, is_art));
                    if is_sci == 1 {
                        scientist_count += 1;
                    }
                    if is_art == 1 {
                        artist_count += 1;
                    }
                }
            }
        }

        // Batch update
        if !updates.is_empty() {
            conn.execute_batch("BEGIN TRANSACTION;")?;
            {
                let mut stmt = conn.prepare_cached(
                    "UPDATE consolidate SET is_scientist = ?1, is_artist = ?2 WHERE wikidata_id = ?3",
                )?;
                for (wid, is_sci, is_art) in &updates {
                    stmt.execute(params![is_sci, is_art, wid])?;
                    updated_count += 1;
                }
            }
            conn.execute_batch("COMMIT;")?;
        }

        pb.inc(batch.len() as u64);
        offset += batch.len() as i64;

        if offset % 500_000 < BATCH_SIZE as i64 {
            log(&format!(
                "[45] Progress: {}/{} processed, {} updated (scientist={}, artist={})",
                offset, total, updated_count, scientist_count, artist_count
            ));
        }
    }
    pb.finish();
    log(&format!(
        "[45] Phase 3 complete: {} updated, {} scientists, {} artists ({})",
        updated_count,
        scientist_count,
        artist_count,
        elapsed(total_start)
    ));

    // ========================================================
    // PHASE 4: Create indexes
    // ========================================================
    log("[45] Phase 4: Creating indexes...");
    let idx_start = Instant::now();
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_consolidate_polity ON consolidate(polity_name);",
    )?;
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_consolidate_year ON consolidate(impact_year);",
    )?;
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_consolidate_scientist ON consolidate(is_scientist);",
    )?;
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_consolidate_artist ON consolidate(is_artist);",
    )?;
    log(&format!(
        "[45] Indexes created ({})",
        elapsed(idx_start)
    ));

    // ========================================================
    // PHASE 5: Export to CSV
    // ========================================================
    log("[45] Phase 5: Exporting to CSV...");
    let csv_start = Instant::now();

    let final_count: i64 =
        conn.query_row("SELECT COUNT(*) FROM consolidate", [], |r| r.get(0))?;

    let mut csv_file = fs::File::create(CSV_PATH)?;
    // Write header
    writeln!(
        csv_file,
        "wikidata_id,name_en,impact_year,polity_name,occupations,gender,references_count,is_scientist,is_artist"
    )?;

    let pb2 = ProgressBar::new(final_count as u64);
    pb2.set_style(
        ProgressStyle::default_bar()
            .template("{msg} [{bar:40}] {pos}/{len} ({eta})")
            .unwrap(),
    );
    pb2.set_message("Exporting CSV");

    let mut csv_offset: i64 = 0;
    let mut csv_rows_written = 0u64;

    loop {
        let mut rows_data: Vec<(
            String,
            String,
            String,
            String,
            String,
            String,
            String,
            i32,
            i32,
        )> = Vec::with_capacity(BATCH_SIZE);
        {
            let mut stmt = conn.prepare_cached(
                "SELECT wikidata_id, name_en, impact_year, polity_name, occupations,
                        gender, references_count, is_scientist, is_artist
                 FROM consolidate
                 ORDER BY rowid
                 LIMIT ?1 OFFSET ?2",
            )?;
            let rows = stmt.query_map(params![BATCH_SIZE as i64, csv_offset], |r| {
                Ok((
                    r.get::<_, String>(0).unwrap_or_default(),
                    r.get::<_, Option<String>>(1)
                        .unwrap_or(None)
                        .unwrap_or_default(),
                    r.get::<_, Option<i32>>(2)
                        .unwrap_or(None)
                        .map_or(String::new(), |v| v.to_string()),
                    r.get::<_, Option<String>>(3)
                        .unwrap_or(None)
                        .unwrap_or_default(),
                    r.get::<_, Option<String>>(4)
                        .unwrap_or(None)
                        .unwrap_or_default(),
                    r.get::<_, Option<String>>(5)
                        .unwrap_or(None)
                        .unwrap_or_default(),
                    r.get::<_, Option<i32>>(6)
                        .unwrap_or(None)
                        .map_or(String::new(), |v| v.to_string()),
                    r.get::<_, i32>(7).unwrap_or(0),
                    r.get::<_, i32>(8).unwrap_or(0),
                ))
            })?;
            for r in rows {
                rows_data.push(r?);
            }
        }

        if rows_data.is_empty() {
            break;
        }

        for (wid, name, year, polity, occs, gender, refs, is_sci, is_art) in &rows_data {
            writeln!(
                csv_file,
                "{},{},{},{},{},{},{},{},{}",
                csv_escape(wid),
                csv_escape(name),
                year,
                csv_escape(polity),
                csv_escape(occs),
                csv_escape(gender),
                refs,
                is_sci,
                is_art,
            )?;
            csv_rows_written += 1;
        }

        pb2.inc(rows_data.len() as u64);
        csv_offset += rows_data.len() as i64;
    }
    pb2.finish();
    csv_file.flush()?;
    log(&format!(
        "[45] CSV exported to {} ({} rows, {})",
        CSV_PATH,
        csv_rows_written,
        elapsed(csv_start)
    ));

    // ========================================================
    // PHASE 6: Final statistics
    // ========================================================
    log("[45] === Final Statistics ===");
    log(&format!("[45] Total rows in consolidate: {}", final_count));
    log(&format!("[45] Scientists: {}", scientist_count));
    log(&format!("[45] Artists: {}", artist_count));

    // Both scientist and artist
    let both: i64 = conn.query_row(
        "SELECT COUNT(*) FROM consolidate WHERE is_scientist = 1 AND is_artist = 1",
        [],
        |r| r.get(0),
    )?;
    log(&format!("[45] Both scientist and artist: {}", both));

    // Neither
    let neither: i64 = conn.query_row(
        "SELECT COUNT(*) FROM consolidate WHERE is_scientist = 0 AND is_artist = 0",
        [],
        |r| r.get(0),
    )?;
    log(&format!(
        "[45] Neither scientist nor artist (writers/other): {}",
        neither
    ));

    // Top 10 polities
    {
        let mut stmt = conn.prepare(
            "SELECT polity_name, COUNT(*) as cnt FROM consolidate
             GROUP BY polity_name ORDER BY cnt DESC LIMIT 10",
        )?;
        let rows: Vec<(String, i64)> = stmt
            .query_map([], |r| {
                Ok((
                    r.get::<_, Option<String>>(0)?.unwrap_or_default(),
                    r.get(1)?,
                ))
            })?
            .filter_map(|r| r.ok())
            .collect();
        log("[45] Top 10 polities:");
        for (polity, cnt) in &rows {
            log(&format!("[45]   {} -> {}", polity, cnt));
        }
    }

    // Gender distribution
    {
        let mut stmt = conn.prepare(
            "SELECT gender, COUNT(*) as cnt FROM consolidate
             GROUP BY gender ORDER BY cnt DESC LIMIT 10",
        )?;
        let rows: Vec<(String, i64)> = stmt
            .query_map([], |r| {
                Ok((
                    r.get::<_, Option<String>>(0)?.unwrap_or_default(),
                    r.get(1)?,
                ))
            })?
            .filter_map(|r| r.ok())
            .collect();
        log("[45] Gender distribution:");
        for (gender, cnt) in &rows {
            log(&format!("[45]   {} -> {}", gender, cnt));
        }
    }

    // Sample rows
    {
        let mut stmt = conn.prepare(
            "SELECT wikidata_id, name_en, impact_year, polity_name, occupations, gender, references_count, is_scientist, is_artist
             FROM consolidate LIMIT 5",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, Option<String>>(1)?,
                r.get::<_, Option<i32>>(2)?,
                r.get::<_, Option<String>>(3)?,
                r.get::<_, Option<String>>(4)?,
                r.get::<_, Option<String>>(5)?,
                r.get::<_, Option<i32>>(6)?,
                r.get::<_, i32>(7)?,
                r.get::<_, i32>(8)?,
            ))
        })?;
        log("[45] Sample rows:");
        for r in rows {
            let (wid, name, year, polity, occs, gender, refs, is_sci, is_art) = r?;
            log(&format!(
                "[45]   {} | {} | {} | {} | {} | {} | refs={} | sci={} art={}",
                wid,
                name.unwrap_or_default(),
                year.unwrap_or(0),
                polity.unwrap_or_default(),
                occs.as_deref().unwrap_or("").chars().take(40).collect::<String>(),
                gender.unwrap_or_default(),
                refs.unwrap_or(0),
                is_sci,
                is_art,
            ));
        }
    }

    log(&format!(
        "=== Step 45 complete ({}) ===",
        elapsed(total_start)
    ));
    Ok(())
}
