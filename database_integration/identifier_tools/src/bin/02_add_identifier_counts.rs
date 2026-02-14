/*
 * Add a 'count' column to identifier_types table
 * counting the number of individuals per identifier type.
 *
 * Run: cargo run --release --bin 03_add_identifier_counts -- ../../data/humans_clean.sqlite3
 */

use anyhow::{Context, Result};
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::Connection;
use std::env;

fn main() -> Result<()> {
    let args: Vec<String> = env::args().collect();
    if args.len() != 2 {
        eprintln!("Usage: {} <database.sqlite3>", args[0]);
        std::process::exit(1);
    }

    let db_path = &args[1];

    println!("============================================================");
    println!("ADD IDENTIFIER COUNTS");
    println!("============================================================\n");

    // Open database
    println!("[1/4] Opening database...");
    let conn = Connection::open(db_path).context("Cannot open database")?;

    // Optimize for speed
    conn.execute_batch(
        "PRAGMA synchronous = OFF;
         PRAGMA journal_mode = MEMORY;
         PRAGMA cache_size = 1000000;",
    )?;

    println!("  Opened {}", db_path);

    // Check if count column exists, add if not
    println!("\n[2/4] Checking schema...");
    let has_count_column: bool = {
        let mut stmt = conn.prepare("PRAGMA table_info(identifier_types)")?;
        let columns: Vec<String> = stmt
            .query_map([], |row| row.get::<_, String>(1))?
            .filter_map(|r| r.ok())
            .collect();
        columns.contains(&"count".to_string())
    };

    if !has_count_column {
        println!("  Adding 'count' column to identifier_types...");
        conn.execute(
            "ALTER TABLE identifier_types ADD COLUMN count INTEGER DEFAULT 0",
            [],
        )
        .context("Failed to add count column")?;
        println!("  Column added.");
    } else {
        println!("  'count' column already exists.");
    }

    // Get total number of property IDs
    println!("\n[3/4] Counting individuals per identifier...");
    let total_props: i64 = conn.query_row(
        "SELECT COUNT(*) FROM identifier_types",
        [],
        |row| row.get(0),
    )?;
    println!("  Processing {} identifier types...", total_props);

    // Create progress bar
    let pb = ProgressBar::new(total_props as u64);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{spinner:.green} [{elapsed_precise}] [{bar:40.cyan/blue}] {pos}/{len} ({eta})")
            .unwrap()
            .progress_chars("#>-"),
    );

    // Count individuals per identifier type using a single efficient query
    // This counts DISTINCT wikidata_ids per property_id
    conn.execute("BEGIN TRANSACTION", [])?;

    // First, compute all counts in one query and store in temp table
    conn.execute(
        "CREATE TEMP TABLE temp_counts AS
         SELECT property_id, COUNT(DISTINCT wikidata_id) as cnt
         FROM identifiers
         GROUP BY property_id",
        [],
    )?;

    // Update identifier_types from temp table
    conn.execute(
        "UPDATE identifier_types
         SET count = COALESCE(
             (SELECT cnt FROM temp_counts WHERE temp_counts.property_id = identifier_types.property_id),
             0
         )",
        [],
    )?;

    // Drop temp table
    conn.execute("DROP TABLE temp_counts", [])?;

    conn.execute("COMMIT", [])?;
    pb.finish_with_message("done");

    // Create index on count for fast sorting
    println!("\n[4/4] Creating index on count...");
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_identifier_types_count ON identifier_types(count DESC)",
        [],
    )?;
    println!("  Index created.");

    // Show top identifiers by count
    println!("\n  Top 15 identifier types by individual count:");
    println!("  {:-<70}", "");
    println!("  {:10} | {:45} | {:>10}", "property_id", "name", "count");
    println!("  {:-<70}", "");

    let mut stmt = conn.prepare(
        "SELECT property_id, name_en, count
         FROM identifier_types
         ORDER BY count DESC
         LIMIT 15",
    )?;

    let mut rows = stmt.query([])?;
    while let Some(row) = rows.next()? {
        let property_id: String = row.get(0)?;
        let name: String = row.get::<_, Option<String>>(1)?.unwrap_or_else(|| "(no name)".to_string());
        let count: i64 = row.get(2)?;

        // Truncate long names
        let display_name = if name.len() > 45 {
            format!("{}...", &name[..42])
        } else {
            name
        };

        println!("  {:10} | {:45} | {:>10}", property_id, display_name, count);
    }
    println!("  {:-<70}", "");

    // Show stats
    let total_with_counts: i64 = conn.query_row(
        "SELECT COUNT(*) FROM identifier_types WHERE count > 0",
        [],
        |row| row.get(0),
    )?;
    let total_identifiers: i64 = conn.query_row(
        "SELECT SUM(count) FROM identifier_types",
        [],
        |row| row.get(0),
    )?;

    println!("\n  Summary:");
    println!("    - {} identifier types with at least 1 individual", total_with_counts);
    println!("    - {} total identifier associations", total_identifiers);

    println!("\n============================================================");
    println!("DONE!");
    println!("============================================================");

    Ok(())
}
