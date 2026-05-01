/// Create individuals_keys table with Wikidata Q-IDs for each individual.
/// Uses streaming JSON deserialization to process entries one at a time,
/// keeping memory usage constant regardless of file size.
/// Processing order: smallest to largest for early feedback.
use anyhow::Result;
use rusqlite::{params, Connection};
use serde::de::{self, DeserializeOwned, MapAccess, Visitor};
use serde::{Deserialize, Deserializer};
use std::fmt;
use std::fs;
use std::io::{BufReader, Write};
use std::marker::PhantomData;
use std::time::Instant;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const DATA_DIR: &str = "data/all_humans";
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

/// Minimal struct that only deserializes the "id" field, skipping "name" etc.
#[derive(Deserialize)]
struct IdObj {
    id: String,
}

/// Execute a batch of UPDATEs within a transaction.
fn flush_batch(
    conn: &Connection,
    sql: &str,
    batch: &[(String, String)],
    updated: &mut usize,
) -> std::result::Result<(), rusqlite::Error> {
    if batch.is_empty() {
        return Ok(());
    }
    conn.execute_batch("BEGIN TRANSACTION;")?;
    {
        let mut stmt = conn.prepare_cached(sql)?;
        for (qid, id_val) in batch {
            *updated += stmt.execute(params![id_val, qid])?;
        }
    }
    conn.execute_batch("COMMIT;")?;
    Ok(())
}

/// Streaming serde Visitor that processes a JSON map entry-by-entry,
/// updating the database in batches without ever loading the full file.
struct StreamMapVisitor<'a, V, F> {
    conn: &'a Connection,
    column: String,
    extract: F,
    _v: PhantomData<V>,
}

impl<'de, 'a, V, F> Visitor<'de> for StreamMapVisitor<'a, V, F>
where
    V: Deserialize<'de>,
    F: Fn(V) -> Option<String>,
{
    type Value = (usize, usize); // (total_entries, updated_rows)

    fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
        f.write_str("a JSON map of QID to value")
    }

    fn visit_map<M>(self, mut access: M) -> std::result::Result<(usize, usize), M::Error>
    where
        M: MapAccess<'de>,
    {
        let sql = format!(
            "UPDATE individuals_keys SET {} = ?1 WHERE wikidata_id = ?2",
            self.column
        );
        let mut total = 0usize;
        let mut updated = 0usize;
        let mut batch: Vec<(String, String)> = Vec::with_capacity(BATCH_SIZE + 1);

        loop {
            let key = match access.next_key::<String>() {
                Ok(Some(k)) => k,
                Ok(None) => break,
                Err(e) => {
                    eprintln!(
                        "    Warning: JSON parse error at key {} ({}), stopping early",
                        total, e
                    );
                    break;
                }
            };
            let val: V = match access.next_value() {
                Ok(v) => v,
                Err(e) => {
                    eprintln!(
                        "    Warning: JSON parse error at value {} ({}), stopping early",
                        total, e
                    );
                    break;
                }
            };
            total += 1;
            if let Some(id_str) = (self.extract)(val) {
                batch.push((key, id_str));
            }

            if batch.len() >= BATCH_SIZE {
                flush_batch(self.conn, &sql, &batch, &mut updated)
                    .map_err(de::Error::custom)?;
                batch.clear();
            }

            if total % 500_000 == 0 {
                println!(
                    "    ...{} entries processed, {} rows updated so far",
                    total, updated
                );
            }
        }

        // Flush remaining
        flush_batch(self.conn, &sql, &batch, &mut updated).map_err(de::Error::custom)?;

        Ok((total, updated))
    }
}

/// Stream a JSON file and update the corresponding column in individuals_keys.
/// Memory usage is O(BATCH_SIZE) regardless of file size.
fn stream_json_and_update<V, F>(
    conn: &Connection,
    json_file: &str,
    column: &str,
    extract: F,
    step_num: u32,
) -> Result<()>
where
    V: DeserializeOwned,
    F: Fn(V) -> Option<String>,
{
    let start = Instant::now();
    let path = format!("{}/{}", DATA_DIR, json_file);
    log(&format!(
        "[41] Phase {}: Streaming {}...",
        step_num, json_file
    ));

    let file = fs::File::open(&path)?;
    let reader = BufReader::with_capacity(32 * 1024 * 1024, file);
    let mut deserializer = serde_json::Deserializer::from_reader(reader);

    let result = deserializer.deserialize_map(StreamMapVisitor::<V, F> {
        conn,
        column: column.to_string(),
        extract,
        _v: PhantomData,
    });

    match result {
        Ok((total, updated)) => {
            log(&format!(
                "[41]   Phase {}: {} entries, {} rows updated ({})",
                step_num, total, updated, elapsed(start)
            ));
        }
        Err(e) => {
            // Truncated JSON files: data already committed in batches, log warning and continue
            log(&format!(
                "[41]   Phase {}: JSON ended early ({}), batches already committed ({})",
                step_num, e, elapsed(start)
            ));
        }
    }
    Ok(())
}

fn main() -> Result<()> {
    let _ = fs::remove_file(TASK_LOG);
    let total_start = Instant::now();
    log("=== Step 41: Create individuals_keys table ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-64000; PRAGMA mmap_size=0;",
    )?;

    // ========================================================
    // PHASE 1: Create the individuals_keys table
    // ========================================================
    log("[41] Phase 1: Creating individuals_keys table...");
    conn.execute_batch("DROP TABLE IF EXISTS individuals_keys;")?;
    conn.execute_batch(
        "CREATE TABLE individuals_keys (
            wikidata_id TEXT PRIMARY KEY,
            birthcity_id TEXT,
            deathcity_id TEXT,
            nationalities_ids TEXT,
            occupations_ids TEXT,
            gender_id TEXT,
            writing_language_ids TEXT
        );",
    )?;
    log("[41] Phase 1: Table created.");

    // ========================================================
    // PHASE 2: Insert all wikidata_ids from individuals
    // ========================================================
    log("[41] Phase 2: Populating wikidata_ids from individuals table...");
    let phase2_start = Instant::now();
    let count = conn.execute(
        "INSERT INTO individuals_keys (wikidata_id)
         SELECT wikidata_id FROM individuals",
        [],
    )?;
    log(&format!(
        "[41] Phase 2: Inserted {} rows ({})",
        count,
        elapsed(phase2_start)
    ));

    // ========================================================
    // PHASES 3-8: Stream each JSON file and update column
    // ========================================================

    // Phase 3: writing_languages (12MB) - smallest first
    stream_json_and_update::<Vec<IdObj>, _>(
        &conn,
        "all_human_writing_languages.json",
        "writing_language_ids",
        |arr: Vec<IdObj>| {
            let ids: Vec<String> = arr.into_iter().map(|o| o.id).collect();
            if ids.is_empty() {
                None
            } else {
                Some(ids.join(";"))
            }
        },
        3,
    )?;

    // Phase 4: deathplaces (96MB)
    stream_json_and_update::<IdObj, _>(
        &conn,
        "all_human_deathplaces.json",
        "deathcity_id",
        |obj: IdObj| Some(obj.id),
        4,
    )?;

    // Phase 5: birthplaces (226MB)
    stream_json_and_update::<IdObj, _>(
        &conn,
        "all_human_birthplaces.json",
        "birthcity_id",
        |obj: IdObj| Some(obj.id),
        5,
    )?;

    // Phase 6: occupations (282MB)
    stream_json_and_update::<Vec<String>, _>(
        &conn,
        "all_human_occupations.json",
        "occupations_ids",
        |arr: Vec<String>| {
            if arr.is_empty() {
                None
            } else {
                Some(arr.join(";"))
            }
        },
        6,
    )?;

    // Phase 7: nationalities (359MB)
    stream_json_and_update::<Vec<IdObj>, _>(
        &conn,
        "all_human_nationalities.json",
        "nationalities_ids",
        |arr: Vec<IdObj>| {
            let ids: Vec<String> = arr.into_iter().map(|o| o.id).collect();
            if ids.is_empty() {
                None
            } else {
                Some(ids.join(";"))
            }
        },
        7,
    )?;

    // Phase 8: genders (510MB) - largest last
    stream_json_and_update::<IdObj, _>(
        &conn,
        "all_human_genders.json",
        "gender_id",
        |obj: IdObj| Some(obj.id),
        8,
    )?;

    // ========================================================
    // PHASE 9: Create indexes
    // ========================================================
    log("[41] Phase 9: Creating indexes...");
    let idx_start = Instant::now();
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_ik_birthcity ON individuals_keys(birthcity_id);",
    )?;
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_ik_deathcity ON individuals_keys(deathcity_id);",
    )?;
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_ik_gender ON individuals_keys(gender_id);",
    )?;
    log(&format!(
        "[41] Phase 9: Indexes created ({})",
        elapsed(idx_start)
    ));

    // ========================================================
    // PHASE 10: Final statistics
    // ========================================================
    log("[41] Phase 10: Final statistics...");
    let total_rows: i64 =
        conn.query_row("SELECT COUNT(*) FROM individuals_keys", [], |r| r.get(0))?;
    let birthcity_filled: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals_keys WHERE birthcity_id IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    let deathcity_filled: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals_keys WHERE deathcity_id IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    let nationalities_filled: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals_keys WHERE nationalities_ids IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    let occupations_filled: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals_keys WHERE occupations_ids IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    let gender_filled: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals_keys WHERE gender_id IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    let writing_lang_filled: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals_keys WHERE writing_language_ids IS NOT NULL",
        [],
        |r| r.get(0),
    )?;

    log("[41] === Final Statistics ===");
    log(&format!("[41] Total rows: {}", total_rows));
    log(&format!(
        "[41]   birthcity_id filled: {} ({:.1}%)",
        birthcity_filled,
        100.0 * birthcity_filled as f64 / total_rows as f64
    ));
    log(&format!(
        "[41]   deathcity_id filled: {} ({:.1}%)",
        deathcity_filled,
        100.0 * deathcity_filled as f64 / total_rows as f64
    ));
    log(&format!(
        "[41]   nationalities_ids filled: {} ({:.1}%)",
        nationalities_filled,
        100.0 * nationalities_filled as f64 / total_rows as f64
    ));
    log(&format!(
        "[41]   occupations_ids filled: {} ({:.1}%)",
        occupations_filled,
        100.0 * occupations_filled as f64 / total_rows as f64
    ));
    log(&format!(
        "[41]   gender_id filled: {} ({:.1}%)",
        gender_filled,
        100.0 * gender_filled as f64 / total_rows as f64
    ));
    log(&format!(
        "[41]   writing_language_ids filled: {} ({:.1}%)",
        writing_lang_filled,
        100.0 * writing_lang_filled as f64 / total_rows as f64
    ));

    // Sample a few rows
    log("[41] Sample rows:");
    {
        let mut stmt = conn.prepare(
            "SELECT wikidata_id, birthcity_id, deathcity_id, nationalities_ids,
                    occupations_ids, gender_id, writing_language_ids
             FROM individuals_keys
             WHERE birthcity_id IS NOT NULL AND nationalities_ids IS NOT NULL
             LIMIT 5",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, Option<String>>(1)?,
                r.get::<_, Option<String>>(2)?,
                r.get::<_, Option<String>>(3)?,
                r.get::<_, Option<String>>(4)?,
                r.get::<_, Option<String>>(5)?,
                r.get::<_, Option<String>>(6)?,
            ))
        })?;
        for r in rows {
            let (wid, bc, dc, nat, occ, gen, wl) = r?;
            log(&format!(
                "[41]   {} | birth={} death={} nat={} occ={} gen={} wl={}",
                wid,
                bc.unwrap_or_default(),
                dc.unwrap_or_default(),
                nat.unwrap_or_default(),
                occ.unwrap_or_default(),
                gen.unwrap_or_default(),
                wl.unwrap_or_default(),
            ));
        }
    }

    log(&format!(
        "=== Step 41 complete ({}) ===",
        elapsed(total_start)
    ));
    Ok(())
}
