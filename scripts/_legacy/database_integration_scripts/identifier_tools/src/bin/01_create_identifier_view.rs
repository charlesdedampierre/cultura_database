/*
 * Create a view that joins individuals with identifiers,
 * showing individual names and identifier names (not just IDs).
 *
 * Run: cargo run --release --bin 02_create_identifier_view -- ../../data/humans_clean.sqlite3
 */

use anyhow::{Context, Result};
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
    println!("CREATE IDENTIFIER VIEW WITH NAMES");
    println!("============================================================\n");

    // Open database
    println!("[1/2] Opening database...");
    let conn = Connection::open(db_path).context("Cannot open database")?;
    println!("  Opened {}", db_path);

    // Create the view
    println!("\n[2/2] Creating view...");

    // Drop existing view if it exists
    conn.execute("DROP VIEW IF EXISTS identifiers_with_names", [])
        .context("Failed to drop existing view")?;

    // Create the view joining all three tables
    let create_view_sql = r#"
        CREATE VIEW identifiers_with_names AS
        SELECT
            i.wikidata_id,
            ind.name_en AS individual_name,
            it.name_en AS identifier_name,
            i.property_id,
            i.value
        FROM identifiers i
        LEFT JOIN individuals ind ON i.wikidata_id = ind.wikidata_id
        LEFT JOIN identifier_types it ON i.property_id = it.property_id
    "#;

    conn.execute(create_view_sql, [])
        .context("Failed to create view")?;

    println!("  View 'identifiers_with_names' created successfully.");

    // Show sample data from the view
    println!("\n  Sample data from view:");
    println!("  {:-<100}", "");
    println!(
        "  {:12} | {:30} | {:25} | {:8} | {}",
        "wikidata_id", "individual_name", "identifier_name", "prop_id", "value"
    );
    println!("  {:-<100}", "");

    let mut stmt = conn.prepare(
        "SELECT wikidata_id, individual_name, identifier_name, property_id, value
         FROM identifiers_with_names
         WHERE individual_name IS NOT NULL AND identifier_name IS NOT NULL
         LIMIT 10",
    )?;

    let mut rows = stmt.query([])?;
    while let Some(row) = rows.next()? {
        let wikidata_id: String = row.get(0)?;
        let individual_name: String = row.get::<_, Option<String>>(1)?.unwrap_or_default();
        let identifier_name: String = row.get::<_, Option<String>>(2)?.unwrap_or_default();
        let property_id: String = row.get(3)?;
        let value: String = row.get(4)?;

        // Truncate long strings for display
        let ind_name = if individual_name.len() > 30 {
            format!("{}...", &individual_name[..27])
        } else {
            individual_name
        };
        let id_name = if identifier_name.len() > 25 {
            format!("{}...", &identifier_name[..22])
        } else {
            identifier_name
        };

        println!(
            "  {:12} | {:30} | {:25} | {:8} | {}",
            wikidata_id, ind_name, id_name, property_id, value
        );
    }
    println!("  {:-<100}", "");

    // Show view schema
    println!("\n  View columns:");
    println!("    - wikidata_id: The Wikidata Q identifier");
    println!("    - individual_name: Name of the person (from individuals table)");
    println!("    - identifier_name: Name of the identifier type (from identifier_types table)");
    println!("    - property_id: The Wikidata P identifier");
    println!("    - value: The identifier value");

    println!("\n============================================================");
    println!("DONE!");
    println!("============================================================");

    Ok(())
}
