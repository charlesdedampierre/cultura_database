/// Clean properties_definition table:
/// - Remove all identifier properties (used_for = 'identifier')
/// - Add table_name and column_name columns showing where each property is used
use anyhow::Result;
use rusqlite::{params, Connection};
use std::fs;
use std::io::Write;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const TASK_LOG: &str = "task.log";

fn log(msg: &str) {
    println!("{}", msg);
    let mut f = fs::OpenOptions::new()
        .append(true)
        .open(TASK_LOG)
        .unwrap();
    writeln!(f, "{}", msg).unwrap();
}

fn main() -> Result<()> {
    log("[DB] 07: Cleaning properties_definition table...");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;")?;

    // Count identifiers before removal
    let id_count: i64 = conn.query_row(
        "SELECT COUNT(*) FROM properties_definition WHERE used_for = 'identifier'",
        [],
        |row| row.get(0),
    )?;
    log(&format!("[DB] Removing {} identifier properties from properties_definition", id_count));

    // Remove identifiers
    conn.execute("DELETE FROM properties_definition WHERE used_for = 'identifier'", [])?;

    let remaining: i64 = conn.query_row(
        "SELECT COUNT(*) FROM properties_definition",
        [],
        |row| row.get(0),
    )?;
    log(&format!("[DB] {} properties remaining after removal", remaining));

    // Add table_name and column_name columns
    let columns: Vec<String> = conn
        .prepare("PRAGMA table_info(properties_definition)")?
        .query_map([], |row| row.get::<_, String>(1))?
        .filter_map(|r| r.ok())
        .collect();

    if !columns.contains(&"table_name".to_string()) {
        conn.execute_batch("ALTER TABLE properties_definition ADD COLUMN table_name TEXT;")?;
        log("[DB] Added table_name column");
    }
    if !columns.contains(&"column_name".to_string()) {
        conn.execute_batch("ALTER TABLE properties_definition ADD COLUMN column_name TEXT;")?;
        log("[DB] Added column_name column");
    }

    // Map known properties to their table/column usage
    let mappings: Vec<(&str, &str, &str)> = vec![
        // Properties that map to individuals table columns
        ("P21", "individuals", "gender"),
        ("P27", "nationalities", "name_en"),
        ("P106", "occupations", "name_en"),
        ("P569", "individuals", "birthdate"),
        ("P570", "individuals", "deathdate"),
        ("P19", "cities", "name_en (birthcity)"),
        ("P20", "cities", "name_en (deathcity)"),
        ("P6886", "writing_languages", "name"),
        ("P31", "occupations / nationalities", "instance_of"),
        ("P17", "cities / nationalities", "modern_country_name"),
        ("P625", "cities / nationalities", "lat, lon"),
        ("P36", "nationalities", "lat, lon (via capital)"),
        ("P30", "modern_country", "continent"),
        ("P298", "modern_country", "iso_a3_code"),
        ("P1566", "cities", "id (GeoNames)"),
    ];

    let mut update_stmt = conn.prepare(
        "UPDATE properties_definition SET table_name = ?1, column_name = ?2 WHERE property_id = ?3"
    )?;

    for (prop_id, table, col) in &mappings {
        update_stmt.execute(params![table, col, prop_id])?;
    }

    // For remaining properties, try to match by used_for field
    conn.execute(
        "UPDATE properties_definition SET table_name = 'individuals', column_name = used_for
         WHERE table_name IS NULL AND used_for IS NOT NULL",
        [],
    )?;

    log("[DB] 07: Done. Cleaned properties_definition.");
    Ok(())
}
