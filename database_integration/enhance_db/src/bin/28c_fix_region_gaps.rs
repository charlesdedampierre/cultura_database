/// Fix region gaps: Add post-500 CE mappings for countries that only had
/// Ancient Mediterranean entries (Turkey, Romania, Slovenia, Cyprus),
/// and extend Vatican City to cover all time periods.
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

fn main() -> Result<()> {
    log("=== Step 28c: Fix region gaps ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
    )?;

    let additions: Vec<(&str, &str, &str, &str, i32, Option<i32>)> = vec![
        // Turkey: Balkans after 500 CE (was only in Greek World -800 to 500)
        ("Eastern Europe", "Balkans", "Turkey", "TUR", 500, None),
        // Romania: Balkans after 500 CE (was only in Greek/Latin World up to 500)
        ("Eastern Europe", "Balkans", "Romania", "ROU", 500, None),
        // Slovenia: Balkans after 500 CE (was only in Latin World -300 to 500)
        ("Eastern Europe", "Balkans", "Slovenia", "SVN", 500, None),
        // Cyprus: MENA / Arabic world after 500 CE (was only in Greek World -800 to 500)
        ("Middle-East and Africa (MENA)", "Arabic world", "Cyprus", "CYP", 500, None),
    ];

    conn.execute_batch("BEGIN TRANSACTION;")?;

    let mut inserted = 0;
    {
        let mut stmt = conn.prepare(
            "INSERT INTO regions (macro_region, region, iso_country_name, iso_a3, start_year, end_year)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
        )?;

        for (macro_r, region, country, iso, start, end) in &additions {
            stmt.execute(rusqlite::params![macro_r, region, country, iso, start, end])?;
            log(&format!("[28c] Added {} ({}) to {} / {} ({}+)", country, iso, macro_r, region, start));
            inserted += 1;
        }
    }

    // Fix Vatican City: extend start_year to -10000
    conn.execute(
        "UPDATE regions SET start_year = -10000 WHERE iso_a3 = 'VAT'",
        [],
    )?;
    log("[28c] Extended Vatican City (VAT) start_year to -10000");

    // Fix San Marino: extend start_year to -10000
    conn.execute(
        "UPDATE regions SET start_year = -10000 WHERE iso_a3 = 'SMR'",
        [],
    )?;
    log("[28c] Extended San Marino (SMR) start_year to -10000");

    // Fix Malta: extend start_year to -10000
    conn.execute(
        "UPDATE regions SET start_year = -10000 WHERE iso_a3 = 'MLT'",
        [],
    )?;
    log("[28c] Extended Malta (MLT) start_year to -10000");

    conn.execute_batch("COMMIT;")?;

    log(&format!("[28c] Inserted {} new entries", inserted));

    // Verify remaining gaps
    let table_exists: bool = conn.query_row(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='individuals_countries'",
        [], |r| r.get::<_, i64>(0)
    ).map(|c| c > 0).unwrap_or(false);

    if table_exists {
        let mut stmt = conn.prepare(
            "SELECT ic.iso_country_name, ic.iso_a3_code, COUNT(*) as cnt
             FROM individuals_countries ic
             JOIN individuals_impact_date iid ON ic.wikidata_id = iid.wikidata_id
             LEFT JOIN regions r ON ic.iso_a3_code = r.iso_a3
             WHERE r.iso_a3 IS NULL
             GROUP BY ic.iso_country_name
             ORDER BY cnt DESC"
        )?;
        let unmapped: Vec<(String, String, i64)> = stmt
            .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?
            .filter_map(|r| r.ok())
            .collect();

        if unmapped.is_empty() {
            log("[28c] No remaining unmapped countries with impact dates!");
        } else {
            log(&format!("[28c] Remaining unmapped: {}", unmapped.len()));
            for (name, iso, cnt) in &unmapped {
                log(&format!("[28c]   {} ({}) -> {}", name, iso, cnt));
            }
        }
    } else {
        log("[28c] individuals_countries table not yet created, skipping unmapped check");
    }

    let total: i64 = conn.query_row("SELECT COUNT(*) FROM regions", [], |r| r.get(0))?;
    log(&format!("[28c] Total regions entries: {}", total));

    log("=== Step 28c complete ===");
    Ok(())
}
