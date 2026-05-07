/*
 * Fast backfill of `individual_name` and `identifier_name` on rows where
 * they are NULL (the rows just inserted by strategy E in
 * `49v2_load_identifiers_to_db.py`).
 *
 * Strategy:
 *  1) Drop idx_identifiers_name (so UPDATE doesn't pay index maintenance per row).
 *  2) Load individuals.wikidata_id -> name_en into a HashMap (~13M entries).
 *  3) Load identifier_types.property_id -> name_en into a HashMap (~5K).
 *  4) Stream NULL-name rows by rowid range, look up names in HashMaps,
 *     issue batched UPDATE inside a transaction.
 *  5) Recreate idx_identifiers_name.
 *
 * Run:
 *   cargo run --release --bin 06_fast_backfill_names -- ../../data/humans_clean.sqlite3
 */

use anyhow::{Context, Result};
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection};
use std::collections::HashMap;
use std::env;
use std::time::Instant;

const CHUNK: i64 = 200_000;

fn main() -> Result<()> {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("Usage: {} <database_path>", args[0]);
        std::process::exit(1);
    }
    let db_path = &args[1];

    let t_overall = Instant::now();
    println!("=== fast backfill names (Rust, rusqlite) ===");
    println!("DB: {}", db_path);

    let mut conn = Connection::open(db_path).context("open db")?;
    conn.pragma_update(None, "journal_mode", "WAL")?;
    conn.pragma_update(None, "synchronous", "OFF")?;
    conn.pragma_update(None, "temp_store", "MEMORY")?;
    conn.pragma_update(None, "cache_size", -2_000_000_i64)?; // 2 GB

    // 1) Drop idx_identifiers_name to save index maintenance per UPDATE.
    println!("\n[1/5] DROP INDEX idx_identifiers_name (if exists)…");
    let t = Instant::now();
    conn.execute("DROP INDEX IF EXISTS idx_identifiers_name", [])?;
    println!("      done in {:.1}s", t.elapsed().as_secs_f64());

    // 2) Load individuals into HashMap.
    println!("\n[2/5] Loading individuals into HashMap…");
    let t = Instant::now();
    let n_indiv: i64 =
        conn.query_row("SELECT COUNT(*) FROM individuals", [], |r| r.get(0))?;
    let mut indiv: HashMap<String, String> =
        HashMap::with_capacity(n_indiv as usize + 1024);
    {
        let mut stmt = conn.prepare(
            "SELECT wikidata_id, name_en FROM individuals WHERE name_en IS NOT NULL",
        )?;
        let mut rows = stmt.query([])?;
        let pb = ProgressBar::new(n_indiv as u64);
        pb.set_style(
            ProgressStyle::default_bar()
                .template("      [{bar:30.cyan/blue}] {pos}/{len} {per_sec} ({eta})")
                .unwrap()
                .progress_chars("=>-"),
        );
        while let Some(row) = rows.next()? {
            let qid: String = row.get(0)?;
            let name: String = row.get(1)?;
            indiv.insert(qid, name);
            pb.inc(1);
        }
        pb.finish_and_clear();
    }
    println!(
        "      loaded {} individuals into RAM in {:.1}s",
        indiv.len(),
        t.elapsed().as_secs_f64()
    );

    // 3) Load identifier_types.
    println!("\n[3/5] Loading identifier_types into HashMap…");
    let t = Instant::now();
    let mut idtypes: HashMap<String, String> = HashMap::with_capacity(16_000);
    {
        let mut stmt = conn.prepare(
            "SELECT property_id, name_en FROM identifier_types WHERE name_en IS NOT NULL",
        )?;
        let mut rows = stmt.query([])?;
        while let Some(row) = rows.next()? {
            let pid: String = row.get(0)?;
            let name: String = row.get(1)?;
            idtypes.insert(pid, name);
        }
    }
    println!(
        "      loaded {} identifier_types in {:.1}s",
        idtypes.len(),
        t.elapsed().as_secs_f64()
    );

    // 4) Stream NULL-name rows by rowid range and bulk UPDATE.
    let n_null: i64 = conn.query_row(
        "SELECT COUNT(*) FROM identifiers WHERE individual_name IS NULL",
        [],
        |r| r.get(0),
    )?;
    let max_rowid: i64 = conn
        .query_row("SELECT MAX(rowid) FROM identifiers", [], |r| r.get(0))?;
    println!(
        "\n[4/5] Backfilling {} NULL rows (max rowid = {})…",
        n_null, max_rowid
    );

    let pb = ProgressBar::new(n_null as u64);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("      [{bar:30.cyan/blue}] {pos}/{len} {per_sec} ({eta})  {msg}")
            .unwrap()
            .progress_chars("=>-"),
    );

    let t_upd = Instant::now();
    let mut total_updated: u64 = 0;
    let mut total_missing_indiv: u64 = 0;

    let mut start: i64 = 0;
    while start <= max_rowid {
        let end = start + CHUNK;

        // Collect candidates from this rowid range.
        let mut candidates: Vec<(i64, String, String)> = Vec::with_capacity(CHUNK as usize);
        {
            let mut stmt = conn.prepare_cached(
                "SELECT rowid, wikidata_id, property_id
                 FROM identifiers
                 WHERE individual_name IS NULL
                   AND rowid > ?1 AND rowid <= ?2",
            )?;
            let mut rows = stmt.query(params![start, end])?;
            while let Some(row) = rows.next()? {
                candidates.push((row.get(0)?, row.get(1)?, row.get(2)?));
            }
        }

        if !candidates.is_empty() {
            let tx = conn.transaction()?;
            {
                let mut upd = tx.prepare_cached(
                    "UPDATE identifiers
                        SET individual_name = ?1,
                            identifier_name = ?2
                      WHERE rowid = ?3",
                )?;
                for (rowid, qid, pid) in &candidates {
                    let i_name = indiv.get(qid);
                    let t_name = idtypes.get(pid);
                    if i_name.is_none() {
                        total_missing_indiv += 1;
                    }
                    upd.execute(params![i_name, t_name, rowid])?;
                    total_updated += 1;
                }
            }
            tx.commit()?;
            pb.inc(candidates.len() as u64);
            pb.set_message(format!(
                "rowid {}/{}",
                end.min(max_rowid),
                max_rowid
            ));
        }
        start = end;
    }
    pb.finish_and_clear();
    println!(
        "      updated {} rows in {:.1}min  ({} had no match in individuals)",
        total_updated,
        t_upd.elapsed().as_secs_f64() / 60.0,
        total_missing_indiv
    );

    // 5) Recreate idx_identifiers_name.
    println!("\n[5/5] CREATE INDEX idx_identifiers_name…");
    let t = Instant::now();
    conn.execute(
        "CREATE INDEX idx_identifiers_name ON identifiers(individual_name)",
        [],
    )?;
    println!("      built in {:.1}s", t.elapsed().as_secs_f64());

    println!(
        "\n=== DONE in {:.1}min ===",
        t_overall.elapsed().as_secs_f64() / 60.0
    );
    Ok(())
}
