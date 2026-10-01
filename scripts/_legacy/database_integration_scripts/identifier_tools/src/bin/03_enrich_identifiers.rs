/*
 * Drop identifiers_with_names view and enrich identifiers table:
 * - Add individual_name (from individuals table)
 * - Add identifier_name (from identifier_types table)
 * - Add url (constructed from formatter URL + value)
 *
 * Run: cargo run --release --bin 05_enrich_identifiers -- ../../data/humans_clean.sqlite3
 */

use anyhow::{Context, Result};
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::Connection;
use std::env;

fn main() -> Result<()> {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("Usage: {} <database_path>", args[0]);
        std::process::exit(1);
    }
    let db_path = &args[1];

    println!("============================================================");
    println!("ENRICH IDENTIFIERS TABLE");
    println!("============================================================");

    // Open database
    println!("\n[1/5] Opening database...");
    let conn = Connection::open(db_path).context("Failed to open database")?;
    println!("  Opened {}", db_path);

    // Drop the view
    println!("\n[2/5] Dropping identifiers_with_names view...");
    match conn.execute("DROP VIEW IF EXISTS identifiers_with_names", []) {
        Ok(_) => println!("  View dropped."),
        Err(e) => println!("  Warning: {}", e),
    }

    // Add columns
    println!("\n[3/5] Adding columns to identifiers table...");
    let columns = [
        ("individual_name", "TEXT"),
        ("identifier_name", "TEXT"),
        ("url", "TEXT"),
    ];

    for (col_name, col_type) in &columns {
        match conn.execute(
            &format!("ALTER TABLE identifiers ADD COLUMN {} {}", col_name, col_type),
            [],
        ) {
            Ok(_) => println!("  Added column: {}", col_name),
            Err(_) => println!("  Column exists: {}", col_name),
        }
    }

    // Count rows to update
    println!("\n[4/5] Populating columns...");
    let total: i64 = conn.query_row(
        "SELECT COUNT(*) FROM identifiers WHERE individual_name IS NULL",
        [],
        |r| r.get(0),
    )?;
    println!("  {} rows to update", total);

    if total == 0 {
        println!("  Nothing to update!");
    } else {
        // Update individual_name from individuals table
        println!("  Updating individual_name...");
        let pb = ProgressBar::new(3);
        pb.set_style(
            ProgressStyle::default_bar()
                .template("  [{bar:40.cyan/blue}] {pos}/{len} {msg}")
                .unwrap()
                .progress_chars("=>-"),
        );

        conn.execute(
            "UPDATE identifiers
             SET individual_name = (
                 SELECT name_en FROM individuals WHERE individuals.wikidata_id = identifiers.wikidata_id
             )
             WHERE individual_name IS NULL",
            [],
        )?;
        pb.set_message("individual_name done");
        pb.inc(1);

        // Update identifier_name from identifier_types table
        conn.execute(
            "UPDATE identifiers
             SET identifier_name = (
                 SELECT name_en FROM identifier_types WHERE identifier_types.property_id = identifiers.property_id
             )
             WHERE identifier_name IS NULL",
            [],
        )?;
        pb.set_message("identifier_name done");
        pb.inc(1);

        // Update URL - need to fetch formatter URLs first
        // The formatter URL pattern is stored as P1630 in Wikidata
        // For now, construct basic URLs for known patterns
        conn.execute(
            "UPDATE identifiers
             SET url = CASE
                 WHEN property_id = 'P214' THEN 'https://viaf.org/viaf/' || value
                 WHEN property_id = 'P227' THEN 'https://d-nb.info/gnd/' || value
                 WHEN property_id = 'P213' THEN 'https://isni.org/isni/' || value
                 WHEN property_id = 'P244' THEN 'https://id.loc.gov/authorities/names/' || value
                 WHEN property_id = 'P269' THEN 'https://www.idref.fr/' || value
                 WHEN property_id = 'P268' THEN 'https://catalogue.bnf.fr/ark:/12148/cb' || value
                 WHEN property_id = 'P345' THEN 'https://www.imdb.com/' || value
                 WHEN property_id = 'P349' THEN 'https://id.ndl.go.jp/auth/ndlna/' || value
                 WHEN property_id = 'P496' THEN 'https://orcid.org/' || value
                 WHEN property_id = 'P2002' THEN 'https://twitter.com/' || value
                 WHEN property_id = 'P2003' THEN 'https://instagram.com/' || value
                 WHEN property_id = 'P2013' THEN 'https://facebook.com/' || value
                 WHEN property_id = 'P2037' THEN 'https://github.com/' || value
                 WHEN property_id = 'P2397' THEN 'https://youtube.com/channel/' || value
                 WHEN property_id = 'P3368' THEN 'https://prabook.com/web/person-view.html?profileId=' || value
                 WHEN property_id = 'P1566' THEN 'https://www.geonames.org/' || value
                 WHEN property_id = 'P646' THEN 'https://www.google.com/search?kgmid=' || value
                 WHEN property_id = 'P1207' THEN 'http://nukat.edu.pl/aut/' || value
                 WHEN property_id = 'P906' THEN 'https://libris.kb.se/auth/' || value
                 ELSE NULL
             END
             WHERE url IS NULL",
            [],
        )?;
        pb.set_message("url done");
        pb.inc(1);
        pb.finish();
    }

    // Create indexes
    println!("\n[5/5] Creating indexes...");
    match conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_identifiers_name ON identifiers(individual_name)",
        [],
    ) {
        Ok(_) => println!("  Index on individual_name created."),
        Err(e) => println!("  Index exists or error: {}", e),
    }

    // Show sample
    println!("\n  Sample data:");
    println!("  {}", "-".repeat(100));
    let mut stmt = conn.prepare(
        "SELECT wikidata_id, individual_name, identifier_name, property_id, substr(value, 1, 20), substr(url, 1, 40)
         FROM identifiers
         WHERE url IS NOT NULL
         LIMIT 10",
    )?;

    let rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, Option<String>>(1)?,
            row.get::<_, Option<String>>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, String>(4)?,
            row.get::<_, Option<String>>(5)?,
        ))
    })?;

    for row in rows {
        let (qid, name, id_name, prop, val, url) = row?;
        println!(
            "  {} | {} | {} | {} | {}",
            qid,
            name.unwrap_or("-".to_string()).chars().take(20).collect::<String>(),
            id_name.unwrap_or("-".to_string()).chars().take(15).collect::<String>(),
            val,
            url.unwrap_or("-".to_string())
        );
    }
    println!("  {}", "-".repeat(100));

    // Stats
    let with_url: i64 = conn.query_row(
        "SELECT COUNT(*) FROM identifiers WHERE url IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    let total_ids: i64 = conn.query_row("SELECT COUNT(*) FROM identifiers", [], |r| r.get(0))?;
    println!("\n  {} / {} identifiers have URLs ({:.1}%)",
             with_url, total_ids, (with_url as f64 / total_ids as f64) * 100.0);

    println!("\n============================================================");
    println!("DONE!");
    println!("============================================================");

    Ok(())
}
