/// Create the `regions` table mapping countries to regions and macro-regions
/// with date constraints (start_year, end_year) based on Cliopatria classification.
use anyhow::Result;
use rusqlite::Connection;
use std::fs;
use std::io::Write;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const TASK_LOG: &str = "task.log";

fn log(msg: &str) {
    println!("{}", msg);
    let mut f = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(TASK_LOG)
        .unwrap();
    writeln!(f, "{}", msg).unwrap();
}

/// Each entry: (macro_region, region, iso_country_name, iso_a3, start_year, end_year)
/// end_year = None means ongoing / no upper bound
/// start_year uses negative numbers for BC (e.g., -800 = 800 BC)
fn get_region_data() -> Vec<(&'static str, &'static str, &'static str, &'static str, i32, Option<i32>)> {
    vec![
        // === Eastern Europe ===
        // Balkans (After 500 CE)
        ("Eastern Europe", "Balkans", "Bulgaria", "BGR", 500, None),
        ("Eastern Europe", "Balkans", "Greece", "GRC", 500, None),
        ("Eastern Europe", "Balkans", "Albania", "ALB", 500, None),
        ("Eastern Europe", "Balkans", "Montenegro", "MNE", 500, None),
        ("Eastern Europe", "Balkans", "Serbia", "SRB", 500, None),
        ("Eastern Europe", "Balkans", "Bosnia and Herzegovina", "BIH", 500, None),
        ("Eastern Europe", "Balkans", "Croatia", "HRV", 500, None),
        ("Eastern Europe", "Balkans", "North Macedonia", "MKD", 500, None),
        // Kosovo not in DB as separate country

        // Central Europe (After 500 CE)
        ("Eastern Europe", "Central Europe", "Latvia", "LVA", 500, None),
        ("Eastern Europe", "Central Europe", "Estonia", "EST", 500, None),
        ("Eastern Europe", "Central Europe", "Slovakia", "SVK", 500, None),
        ("Eastern Europe", "Central Europe", "Lithuania", "LTU", 500, None),
        ("Eastern Europe", "Central Europe", "Czech Republic", "CZE", 500, None),
        ("Eastern Europe", "Central Europe", "Poland", "POL", 500, None),
        ("Eastern Europe", "Central Europe", "Hungary", "HUN", 500, None),

        // East Slavic (After 500 CE)
        ("Eastern Europe", "East Slavic", "Belarus", "BLR", 500, None),
        ("Eastern Europe", "East Slavic", "Russia", "RUS", 500, None),
        ("Eastern Europe", "East Slavic", "Ukraine", "UKR", 500, None),

        // === Western Europe ===
        // British Islands (After 500 CE)
        ("Western Europe", "British Islands", "Ireland", "IRL", 500, None),
        ("Western Europe", "British Islands", "United Kingdom", "GBR", 500, None),

        // France (After 500 CE)
        ("Western Europe", "France", "France", "FRA", 500, None),

        // German world (After 500 CE)
        ("Western Europe", "German world", "Germany", "DEU", 500, None),
        ("Western Europe", "German world", "Switzerland", "CHE", 500, None),
        ("Western Europe", "German world", "Austria", "AUT", 500, None),

        // Portugal (After 500 CE)
        ("Western Europe", "Portugal", "Portugal", "PRT", 500, None),

        // Spain (after 500 CE)
        ("Western Europe", "Spain", "Spain", "ESP", 500, None),

        // Italy (after 500 CE)
        ("Western Europe", "Italy", "Italy", "ITA", 500, None),

        // Low countries (After 500 CE)
        ("Western Europe", "Low countries", "Kingdom of the Netherlands", "NLD", 500, None),
        ("Western Europe", "Low countries", "Belgium", "BEL", 500, None),

        // Nordic countries (After 500 CE)
        ("Western Europe", "Nordic countries", "Denmark", "DNK", 500, None),
        ("Western Europe", "Nordic countries", "Norway", "NOR", 500, None),
        ("Western Europe", "Nordic countries", "Sweden", "SWE", 500, None),
        ("Western Europe", "Nordic countries", "Finland", "FIN", 500, None),
        ("Western Europe", "Nordic countries", "Iceland", "ISL", 500, None),

        // === Middle-East and Africa (MENA) ===
        // Arabic world (no date constraint specified => all time)
        ("Middle-East and Africa (MENA)", "Arabic world", "Tunisia", "TUN", -10000, None),
        ("Middle-East and Africa (MENA)", "Arabic world", "Algeria", "DZA", -10000, None),
        ("Middle-East and Africa (MENA)", "Arabic world", "Morocco", "MAR", -10000, None),
        ("Middle-East and Africa (MENA)", "Arabic world", "Libya", "LBY", -10000, None),
        ("Middle-East and Africa (MENA)", "Arabic world", "Egypt", "EGY", -10000, None),
        ("Middle-East and Africa (MENA)", "Arabic world", "Palestine", "PSE", -10000, None),
        ("Middle-East and Africa (MENA)", "Arabic world", "Israel", "ISR", -10000, None),
        ("Middle-East and Africa (MENA)", "Arabic world", "Lebanon", "LBN", -10000, None),
        ("Middle-East and Africa (MENA)", "Arabic world", "Syria", "SYR", -10000, None),
        ("Middle-East and Africa (MENA)", "Arabic world", "Jordan", "JOR", -10000, None),
        ("Middle-East and Africa (MENA)", "Arabic world", "Iraq", "IRQ", -10000, None),
        ("Middle-East and Africa (MENA)", "Arabic world", "Kuwait", "KWT", -10000, None),
        ("Middle-East and Africa (MENA)", "Arabic world", "Oman", "OMN", -10000, None),
        ("Middle-East and Africa (MENA)", "Arabic world", "United Arab Emirates", "ARE", -10000, None),
        ("Middle-East and Africa (MENA)", "Arabic world", "Saudi Arabia", "SAU", -10000, None),
        ("Middle-East and Africa (MENA)", "Arabic world", "Bahrain", "BHR", -10000, None),
        ("Middle-East and Africa (MENA)", "Arabic world", "Yemen", "YEM", -10000, None),

        // Persian World (no date constraint => all time)
        ("Middle-East and Africa (MENA)", "Persian World", "Iran", "IRN", -10000, None),
        ("Middle-East and Africa (MENA)", "Persian World", "Afghanistan", "AFG", -10000, None),
        ("Middle-East and Africa (MENA)", "Persian World", "Kyrgyzstan", "KGZ", -10000, None),
        ("Middle-East and Africa (MENA)", "Persian World", "Uzbekistan", "UZB", -10000, None),
        ("Middle-East and Africa (MENA)", "Persian World", "Turkmenistan", "TKM", -10000, None),
        ("Middle-East and Africa (MENA)", "Persian World", "Azerbaijan", "AZE", -10000, None),

        // === Asia ===
        // Chinese World (no date constraint => all time)
        ("Asia", "Chinese World", "People's Republic of China", "CHN", -10000, None),
        ("Asia", "Chinese World", "Mongolia", "MNG", -10000, None),
        ("Asia", "Chinese World", "Taiwan", "TWN", -10000, None),

        // Indian World (no date constraint => all time)
        ("Asia", "Indian World", "India", "IND", -10000, None),
        ("Asia", "Indian World", "Pakistan", "PAK", -10000, None),
        ("Asia", "Indian World", "Bangladesh", "BGD", -10000, None),
        ("Asia", "Indian World", "Sri Lanka", "LKA", -10000, None),
        ("Asia", "Indian World", "Nepal", "NPL", -10000, None),

        // Japan (no date constraint => all time)
        ("Asia", "Japan", "Japan", "JPN", -10000, None),

        // Korea (no date constraint => all time)
        ("Asia", "Korea", "South Korea", "KOR", -10000, None),
        ("Asia", "Korea", "North Korea", "PRK", -10000, None),

        // === Ancient Mediterranean ===
        // Greek World (800BC to 500CE)
        ("Ancient Mediterranean", "Greek World", "Ukraine", "UKR", -800, Some(500)),
        ("Ancient Mediterranean", "Greek World", "Albania", "ALB", -800, Some(500)),
        ("Ancient Mediterranean", "Greek World", "Montenegro", "MNE", -800, Some(500)),
        // Kosovo not in DB
        ("Ancient Mediterranean", "Greek World", "Turkey", "TUR", -800, Some(500)),
        ("Ancient Mediterranean", "Greek World", "Greece", "GRC", -800, Some(500)),
        ("Ancient Mediterranean", "Greek World", "Bulgaria", "BGR", -800, Some(500)),
        ("Ancient Mediterranean", "Greek World", "Romania", "ROU", -800, Some(500)),
        ("Ancient Mediterranean", "Greek World", "France", "FRA", -800, Some(-300)),  // until 300BC
        ("Ancient Mediterranean", "Greek World", "Italy", "ITA", -800, Some(-300)),   // until 300BC
        ("Ancient Mediterranean", "Greek World", "Spain", "ESP", -800, Some(-300)),   // until 300BC
        ("Ancient Mediterranean", "Greek World", "Libya", "LBY", -800, Some(500)),
        ("Ancient Mediterranean", "Greek World", "Egypt", "EGY", -800, Some(500)),
        ("Ancient Mediterranean", "Greek World", "Israel", "ISR", -800, Some(500)),
        ("Ancient Mediterranean", "Greek World", "Palestine", "PSE", -800, Some(500)),
        ("Ancient Mediterranean", "Greek World", "Lebanon", "LBN", -800, Some(500)),
        ("Ancient Mediterranean", "Greek World", "Syria", "SYR", -800, Some(500)),
        ("Ancient Mediterranean", "Greek World", "Jordan", "JOR", -800, Some(500)),
        ("Ancient Mediterranean", "Greek World", "Cyprus", "CYP", -800, Some(500)),
        ("Ancient Mediterranean", "Greek World", "Iraq", "IRQ", -800, Some(500)),

        // Latin World (300BC to 500CE)
        ("Ancient Mediterranean", "Latin World", "Tunisia", "TUN", -300, Some(500)),
        ("Ancient Mediterranean", "Latin World", "Algeria", "DZA", -300, Some(500)),
        ("Ancient Mediterranean", "Latin World", "Morocco", "MAR", -300, Some(500)),
        ("Ancient Mediterranean", "Latin World", "Romania", "ROU", -300, Some(500)),
        ("Ancient Mediterranean", "Latin World", "Croatia", "HRV", -300, Some(500)),
        ("Ancient Mediterranean", "Latin World", "Serbia", "SRB", -300, Some(500)),
        ("Ancient Mediterranean", "Latin World", "Bosnia and Herzegovina", "BIH", -300, Some(500)),
        ("Ancient Mediterranean", "Latin World", "Slovenia", "SVN", -300, Some(500)),
        ("Ancient Mediterranean", "Latin World", "France", "FRA", -300, Some(500)),
        ("Ancient Mediterranean", "Latin World", "United Kingdom", "GBR", -300, Some(500)),
        ("Ancient Mediterranean", "Latin World", "Germany", "DEU", -300, Some(500)),
        ("Ancient Mediterranean", "Latin World", "Switzerland", "CHE", -300, Some(500)),
        ("Ancient Mediterranean", "Latin World", "Austria", "AUT", -300, Some(500)),
        ("Ancient Mediterranean", "Latin World", "Spain", "ESP", -300, Some(500)),
        ("Ancient Mediterranean", "Latin World", "Portugal", "PRT", -300, Some(500)),
        ("Ancient Mediterranean", "Latin World", "Italy", "ITA", -300, Some(500)),
    ]
}

fn main() -> Result<()> {
    log("=== Step 28: Create regions table ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // Drop and create the regions table
    log("[28] Creating regions table...");
    conn.execute_batch("DROP TABLE IF EXISTS regions;")?;
    conn.execute_batch(
        "CREATE TABLE regions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            macro_region TEXT NOT NULL,
            region TEXT NOT NULL,
            iso_country_name TEXT NOT NULL,
            iso_a3 TEXT NOT NULL,
            start_year INTEGER NOT NULL,
            end_year INTEGER
        );",
    )?;

    let data = get_region_data();
    let total = data.len();
    log(&format!("[28] Inserting {} region-country mappings...", total));

    conn.execute_batch("BEGIN TRANSACTION;")?;
    {
        let mut stmt = conn.prepare(
            "INSERT INTO regions (macro_region, region, iso_country_name, iso_a3, start_year, end_year)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
        )?;

        for (macro_region, region, country, iso, start, end) in &data {
            stmt.execute(rusqlite::params![macro_region, region, country, iso, start, end])?;
        }
    }
    conn.execute_batch("COMMIT;")?;

    // Create indexes
    log("[28] Creating indexes...");
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_regions_iso ON regions(iso_a3);")?;
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_regions_macro ON regions(macro_region);",
    )?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_regions_region ON regions(region);")?;

    // Verify
    let count: i64 = conn.query_row("SELECT COUNT(*) FROM regions", [], |r| r.get(0))?;
    log(&format!("[28] Total rows in regions table: {}", count));

    // Show summary by macro_region
    let mut stmt = conn.prepare(
        "SELECT macro_region, COUNT(*) FROM regions GROUP BY macro_region ORDER BY macro_region",
    )?;
    let rows: Vec<(String, i64)> = stmt
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[28] Summary by macro_region:");
    for (mr, cnt) in &rows {
        log(&format!("[28]   {} -> {} country mappings", mr, cnt));
    }

    // Show summary by region
    let mut stmt = conn.prepare(
        "SELECT macro_region, region, COUNT(*), start_year, end_year FROM regions GROUP BY macro_region, region ORDER BY macro_region, region",
    )?;
    let rows: Vec<(String, String, i64, i32, Option<i32>)> = stmt
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[28] Detail by region:");
    for (mr, reg, cnt, start, end) in &rows {
        let end_str = match end {
            Some(e) => format!("{}", e),
            None => "ongoing".to_string(),
        };
        log(&format!(
            "[28]   {} / {} -> {} countries ({} to {})",
            mr, reg, cnt, start, end_str
        ));
    }

    log("=== Step 28 complete ===");
    Ok(())
}
