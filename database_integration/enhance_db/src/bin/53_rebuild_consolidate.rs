/// Rebuild consolidate table from individuals_cliopatria + individuals + polities_cliopatria.
///
/// Associates each individual to specific polities via polity_id (semicolon-separated).
/// An individual can belong to multiple overlapping polities (e.g. "Han" and "(Han)").
///
/// polity_id in individuals_cliopatria is now TEXT (semicolon-separated IDs).
/// This step splits those IDs, resolves each to the latest name from polities_cliopatria
/// (updated in steps 47-49), and stores semicolon-separated names and IDs in consolidate.
///
/// Columns:
///   wikidata_id, name_en, impact_year, polity_id (TEXT, ;-separated),
///   polity_name (TEXT, ;-separated), occupations (;-separated),
///   gender, references_count, is_scientist (0/1), is_artist (0/1)
///
/// Phase 1: Build occupation_id -> meta_occupation lookup
/// Phase 2: Build polity_id -> latest name lookup from polities_cliopatria
/// Phase 3: Populate consolidate (resolve polity names from IDs)
/// Phase 4: Update is_scientist / is_artist
/// Phase 5: Create indexes
/// Phase 6: Update polities_cliopatria.number_individuals
/// Phase 7: Export to CSV
/// Phase 8: Statistics
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
    log("=== Step 53: Rebuild consolidate table (multi-polity, polity_id based) ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // ========================================================
    // PHASE 1: Build occupation_id -> meta_occupation lookup
    // ========================================================
    log("[53] Phase 1: Building occupation lookup...");
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
        "[53] Occupation lookup: {} entries",
        occ_lookup.len()
    ));

    // ========================================================
    // PHASE 2: Build polity_id -> latest name from polities_cliopatria
    // ========================================================
    log("[53] Phase 2: Building polity_id -> name lookup from polities_cliopatria...");
    let mut polity_id_to_name: HashMap<i64, String> = HashMap::new();
    {
        let mut stmt = conn.prepare("SELECT id, name FROM polities_cliopatria")?;
        let rows = stmt.query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?)))?;
        for r in rows {
            let (id, name) = r?;
            polity_id_to_name.insert(id, name);
        }
    }
    log(&format!(
        "[53] Polity lookup: {} entries",
        polity_id_to_name.len()
    ));

    // ========================================================
    // PHASE 3: Create and populate consolidate table
    //   polity_id is TEXT (semicolon-separated) from individuals_cliopatria
    //   polity_name is resolved fresh from polities_cliopatria via each ID
    // ========================================================
    log("[53] Phase 3: Creating and populating consolidate table...");
    let phase3_start = Instant::now();

    conn.execute_batch("DROP TABLE IF EXISTS consolidate;")?;
    conn.execute_batch(
        "CREATE TABLE consolidate (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            impact_year INTEGER,
            polity_id TEXT,
            polity_name TEXT,
            occupations TEXT,
            gender TEXT,
            references_count INTEGER,
            is_scientist INTEGER DEFAULT 0,
            is_artist INTEGER DEFAULT 0
        );",
    )?;
    log("[53] Table created with polity_id TEXT column (semicolon-separated).");

    // Read from individuals_cliopatria in batches, resolve polity names from IDs,
    // and insert into consolidate
    let ic_count: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals_cliopatria ic JOIN individuals i ON ic.wikidata_id = i.wikidata_id",
        [],
        |r| r.get(0),
    )?;
    log(&format!("[53] Individuals to process: {}", ic_count));

    let pb = ProgressBar::new(ic_count as u64);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{msg} [{bar:40}] {pos}/{len} ({eta})")
            .unwrap(),
    );
    pb.set_message("Building consolidate");

    let mut offset: i64 = 0;
    let mut total_inserted = 0u64;
    let mut orphaned_ids = 0u64;

    loop {
        let mut batch: Vec<(
            String,          // wikidata_id
            Option<String>,  // name_en
            Option<i32>,     // impact_date
            Option<String>,  // polity_id (semicolon-separated)
            Option<String>,  // occupations_en
            Option<String>,  // gender
            Option<i32>,     // identifiers_count
        )> = Vec::with_capacity(BATCH_SIZE);
        {
            let mut stmt = conn.prepare_cached(
                "SELECT ic.wikidata_id, ic.name_en, ic.impact_date, ic.polity_id,
                        i.occupations_en, i.gender, i.identifiers_count
                 FROM individuals_cliopatria ic
                 JOIN individuals i ON ic.wikidata_id = i.wikidata_id
                 ORDER BY ic.rowid
                 LIMIT ?1 OFFSET ?2",
            )?;
            let rows = stmt.query_map(params![BATCH_SIZE as i64, offset], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, Option<String>>(1)?,
                    r.get::<_, Option<i32>>(2)?,
                    r.get::<_, Option<String>>(3)?,
                    r.get::<_, Option<String>>(4).unwrap_or(None), // occupations_en may have invalid UTF-8
                    r.get::<_, Option<String>>(5).unwrap_or(None), // gender may have invalid UTF-8
                    r.get::<_, Option<i32>>(6)?,
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
                "INSERT OR IGNORE INTO consolidate
                 (wikidata_id, name_en, impact_year, polity_id, polity_name, occupations, gender, references_count)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
            )?;

            for (wikidata_id, name_en, impact_date, polity_id_str, occupations, gender, refs) in &batch {
                // Resolve polity names from semicolon-separated IDs
                let (resolved_ids, resolved_names) = if let Some(pid_str) = polity_id_str {
                    let mut ids: Vec<String> = Vec::new();
                    let mut names: Vec<String> = Vec::new();
                    for pid in pid_str.split(';') {
                        let pid = pid.trim();
                        if let Ok(id) = pid.parse::<i64>() {
                            if let Some(name) = polity_id_to_name.get(&id) {
                                ids.push(pid.to_string());
                                names.push(name.clone());
                            } else {
                                // polity_id not found in polities_cliopatria (orphaned)
                                orphaned_ids += 1;
                            }
                        }
                    }
                    if ids.is_empty() {
                        (None, None)
                    } else {
                        (Some(ids.join(";")), Some(names.join(";")))
                    }
                } else {
                    (None, None)
                };

                // Skip if no valid polity resolved
                if resolved_ids.is_none() {
                    continue;
                }

                insert.execute(params![
                    wikidata_id,
                    name_en,
                    impact_date,
                    resolved_ids,
                    resolved_names,
                    occupations,
                    gender,
                    refs
                ])?;
                total_inserted += 1;
            }
        }
        conn.execute_batch("COMMIT;")?;

        pb.inc(batch.len() as u64);
        offset += batch.len() as i64;

        if offset % 500_000 < BATCH_SIZE as i64 {
            log(&format!(
                "[53] Progress: {}/{} processed, {} inserted",
                offset, ic_count, total_inserted
            ));
        }
    }
    pb.finish();
    log(&format!(
        "[53] Phase 3: Inserted {} rows ({}) [orphaned polity_ids: {}]",
        total_inserted,
        elapsed(phase3_start),
        orphaned_ids
    ));

    // ========================================================
    // PHASE 4: Update is_scientist / is_artist flags
    // ========================================================
    let total: i64 = conn.query_row("SELECT COUNT(*) FROM consolidate", [], |r| r.get(0))?;
    log(&format!(
        "[53] Phase 4: Updating is_scientist/is_artist for {} rows...",
        total
    ));

    let pb2 = ProgressBar::new(total as u64);
    pb2.set_style(
        ProgressStyle::default_bar()
            .template("{msg} [{bar:40}] {pos}/{len} ({eta})")
            .unwrap(),
    );
    pb2.set_message("Updating scientist/artist flags");

    let mut sci_offset: i64 = 0;
    let mut scientist_count = 0u64;
    let mut artist_count = 0u64;
    let mut updated_count = 0u64;

    loop {
        let mut batch: Vec<String> = Vec::with_capacity(BATCH_SIZE);
        {
            let mut stmt = conn.prepare_cached(
                "SELECT wikidata_id FROM consolidate ORDER BY rowid LIMIT ?1 OFFSET ?2",
            )?;
            let rows = stmt.query_map(params![BATCH_SIZE as i64, sci_offset], |r| {
                r.get::<_, String>(0)
            })?;
            for r in rows {
                batch.push(r?);
            }
        }

        if batch.is_empty() {
            break;
        }

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

        pb2.inc(batch.len() as u64);
        sci_offset += batch.len() as i64;

        if sci_offset % 500_000 < BATCH_SIZE as i64 {
            log(&format!(
                "[53] Progress: {}/{} processed, {} updated (scientist={}, artist={})",
                sci_offset, total, updated_count, scientist_count, artist_count
            ));
        }
    }
    pb2.finish();
    log(&format!(
        "[53] Phase 4 complete: {} updated, {} scientists, {} artists ({})",
        updated_count,
        scientist_count,
        artist_count,
        elapsed(total_start)
    ));

    // ========================================================
    // PHASE 5: Create indexes
    // ========================================================
    log("[53] Phase 5: Creating indexes...");
    let idx_start = Instant::now();
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_consolidate_polity_id ON consolidate(polity_id);",
    )?;
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
        "[53] Indexes created ({})",
        elapsed(idx_start)
    ));

    // ========================================================
    // PHASE 6: Update polities_cliopatria.number_individuals
    //   Split semicolon-separated polity_id and count each occurrence
    // ========================================================
    log("[53] Phase 6: Updating polities_cliopatria.number_individuals from consolidate...");
    conn.execute_batch("UPDATE polities_cliopatria SET number_individuals = 0;")?;

    let mut counts_by_id: HashMap<i64, i64> = HashMap::new();
    {
        let mut stmt = conn.prepare("SELECT polity_id FROM consolidate WHERE polity_id IS NOT NULL")?;
        let rows = stmt.query_map([], |r| r.get::<_, String>(0))?;
        for r in rows {
            let pid_str = r?;
            for pid in pid_str.split(';') {
                let pid = pid.trim();
                if let Ok(id) = pid.parse::<i64>() {
                    *counts_by_id.entry(id).or_insert(0) += 1;
                }
            }
        }
    }

    conn.execute_batch("BEGIN TRANSACTION;")?;
    {
        let mut update =
            conn.prepare("UPDATE polities_cliopatria SET number_individuals = ?1 WHERE id = ?2")?;
        for (id, cnt) in &counts_by_id {
            update.execute(params![cnt, id])?;
        }
    }
    conn.execute_batch("COMMIT;")?;

    let polities_with_individuals: usize = counts_by_id.values().filter(|&&c| c > 0).count();
    log(&format!(
        "[53] Updated number_individuals for {} polities",
        polities_with_individuals
    ));

    // ========================================================
    // PHASE 7: Export to CSV
    // ========================================================
    log("[53] Phase 7: Exporting to CSV...");
    let csv_start = Instant::now();

    let final_count: i64 =
        conn.query_row("SELECT COUNT(*) FROM consolidate", [], |r| r.get(0))?;

    let mut csv_file = std::io::BufWriter::new(fs::File::create(CSV_PATH)?);
    writeln!(
        csv_file,
        "wikidata_id,name_en,impact_year,polity_id,polity_name,occupations,gender,references_count,is_scientist,is_artist"
    )?;

    let pb3 = ProgressBar::new(final_count as u64);
    pb3.set_style(
        ProgressStyle::default_bar()
            .template("{msg} [{bar:40}] {pos}/{len} ({eta})")
            .unwrap(),
    );
    pb3.set_message("Exporting CSV");

    let mut csv_rows_written = 0u64;

    {
        let mut stmt = conn.prepare(
            "SELECT wikidata_id, name_en, impact_year, polity_id, polity_name, occupations,
                    gender, references_count, is_scientist, is_artist
             FROM consolidate",
        )?;
        let mut rows = stmt.query([])?;
        while let Some(r) = rows.next()? {
            let wid: String = r.get::<_, String>(0).unwrap_or_default();
            let name: String = r.get::<_, Option<String>>(1).unwrap_or(None).unwrap_or_default();
            let year: String = r.get::<_, Option<i32>>(2).unwrap_or(None).map_or(String::new(), |v| v.to_string());
            let pid: String = r.get::<_, Option<String>>(3).unwrap_or(None).unwrap_or_default();
            let polity: String = r.get::<_, Option<String>>(4).unwrap_or(None).unwrap_or_default();
            let occs: String = r.get::<_, Option<String>>(5).unwrap_or(None).unwrap_or_default();
            let gender: String = r.get::<_, Option<String>>(6).unwrap_or(None).unwrap_or_default();
            let refs: String = r.get::<_, Option<i32>>(7).unwrap_or(None).map_or(String::new(), |v| v.to_string());
            let is_sci: i32 = r.get::<_, i32>(8).unwrap_or(0);
            let is_art: i32 = r.get::<_, i32>(9).unwrap_or(0);

            writeln!(
                csv_file,
                "{},{},{},{},{},{},{},{},{},{}",
                csv_escape(&wid),
                csv_escape(&name),
                year,
                csv_escape(&pid),
                csv_escape(&polity),
                csv_escape(&occs),
                csv_escape(&gender),
                refs,
                is_sci,
                is_art,
            )?;
            csv_rows_written += 1;

            if csv_rows_written % 500_000 == 0 {
                pb3.set_position(csv_rows_written);
            }
        }
    }
    pb3.finish();
    csv_file.flush()?;
    log(&format!(
        "[53] CSV exported to {} ({} rows, {})",
        CSV_PATH,
        csv_rows_written,
        elapsed(csv_start)
    ));

    // ========================================================
    // PHASE 8: Final statistics
    // ========================================================
    log("[53] === Final Statistics ===");
    log(&format!("[53] Total rows in consolidate: {}", final_count));
    log(&format!("[53] Scientists: {}", scientist_count));
    log(&format!("[53] Artists: {}", artist_count));

    let both: i64 = conn.query_row(
        "SELECT COUNT(*) FROM consolidate WHERE is_scientist = 1 AND is_artist = 1",
        [],
        |r| r.get(0),
    )?;
    log(&format!("[53] Both scientist and artist: {}", both));

    let neither: i64 = conn.query_row(
        "SELECT COUNT(*) FROM consolidate WHERE is_scientist = 0 AND is_artist = 0",
        [],
        |r| r.get(0),
    )?;
    log(&format!(
        "[53] Neither scientist nor artist (writers/other): {}",
        neither
    ));

    // With/without impact_year
    let with_year: i64 = conn.query_row(
        "SELECT COUNT(*) FROM consolidate WHERE impact_year IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    let without_year: i64 = conn.query_row(
        "SELECT COUNT(*) FROM consolidate WHERE impact_year IS NULL",
        [],
        |r| r.get(0),
    )?;
    log(&format!(
        "[53] With impact_year: {}, Without (URL fallback): {}",
        with_year, without_year
    ));

    // Multi-polity individuals
    let multi_polity: i64 = conn.query_row(
        "SELECT COUNT(*) FROM consolidate WHERE polity_id LIKE '%;%'",
        [],
        |r| r.get(0),
    )?;
    let single_polity = final_count - multi_polity;
    log(&format!(
        "[53] Single-polity individuals: {}, Multi-polity individuals: {}",
        single_polity, multi_polity
    ));

    // Top 20 polities by number_individuals (from polities_cliopatria)
    {
        let mut stmt = conn.prepare(
            "SELECT pc.id, pc.name, pc.number_individuals
             FROM polities_cliopatria pc
             ORDER BY pc.number_individuals DESC
             LIMIT 20",
        )?;
        let rows: Vec<(i64, String, i64)> = stmt
            .query_map([], |r| {
                Ok((
                    r.get::<_, i64>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, i64>(2)?,
                ))
            })?
            .filter_map(|r| r.ok())
            .collect();
        log("[53] Top 20 polities (by number_individuals from polities_cliopatria):");
        for (pid, polity, cnt) in &rows {
            log(&format!("[53]   [id={}] {} -> {}", pid, polity, cnt));
        }
    }

    // Polities with duplicate names but different IDs
    {
        let mut stmt = conn.prepare(
            "SELECT name, COUNT(*) as id_count
             FROM polities_cliopatria
             WHERE number_individuals > 0
             GROUP BY name
             HAVING id_count > 1
             ORDER BY id_count DESC
             LIMIT 10",
        )?;
        let rows: Vec<(String, i64)> = stmt
            .query_map([], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get(1)?,
                ))
            })?
            .filter_map(|r| r.ok())
            .collect();
        if !rows.is_empty() {
            log("[53] Polity names with multiple distinct IDs (with individuals):");
            for (name, id_count) in &rows {
                log(&format!("[53]   {} -> {} distinct polity_ids", name, id_count));
            }
        } else {
            log("[53] No polity name duplicates with different IDs found.");
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
        log("[53] Gender distribution:");
        for (gender, cnt) in &rows {
            log(&format!("[53]   {} -> {}", gender, cnt));
        }
    }

    // Sample rows
    {
        let mut stmt = conn.prepare(
            "SELECT wikidata_id, name_en, impact_year, polity_id, polity_name, occupations, gender, references_count, is_scientist, is_artist
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
                r.get::<_, Option<String>>(6)?,
                r.get::<_, Option<i32>>(7)?,
                r.get::<_, i32>(8)?,
                r.get::<_, i32>(9)?,
            ))
        })?;
        log("[53] Sample rows:");
        for r in rows {
            let (wid, name, year, pid, polity, occs, gender, refs, is_sci, is_art) = r?;
            log(&format!(
                "[53]   {} | {} | {} | polity_ids={} | {} | {} | {} | refs={} | sci={} art={}",
                wid,
                name.unwrap_or_default(),
                year.unwrap_or(0),
                pid.unwrap_or_default(),
                polity.unwrap_or_default(),
                occs.as_deref().unwrap_or("").chars().take(40).collect::<String>(),
                gender.unwrap_or_default(),
                refs.unwrap_or(0),
                is_sci,
                is_art,
            ));
        }
    }

    // Sample multi-polity rows
    {
        let mut stmt = conn.prepare(
            "SELECT wikidata_id, name_en, impact_year, polity_id, polity_name
             FROM consolidate
             WHERE polity_id LIKE '%;%'
             LIMIT 5",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, Option<String>>(1)?,
                r.get::<_, Option<i32>>(2)?,
                r.get::<_, Option<String>>(3)?,
                r.get::<_, Option<String>>(4)?,
            ))
        })?;
        log("[53] Sample multi-polity rows:");
        for r in rows {
            let (wid, name, year, pid, polity) = r?;
            log(&format!(
                "[53]   {} | {} | {} | ids={} | names={}",
                wid,
                name.unwrap_or_default(),
                year.unwrap_or(0),
                pid.unwrap_or_default(),
                polity.unwrap_or_default(),
            ));
        }
    }

    log(&format!(
        "=== Step 53 complete ({}) ===",
        elapsed(total_start)
    ));
    Ok(())
}
