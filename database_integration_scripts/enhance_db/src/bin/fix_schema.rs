/// Fix corrupted sqlite_master by creating missing tables/indexes
/// that are on the damaged page.
///
/// Strategy: open db, create a new temporary db, dump what we can,
/// then reconstruct missing schema entries.
use rusqlite::Connection;

fn main() {
    let conn = Connection::open("data/humans_clean.sqlite3").unwrap();
    conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;").ok();

    // First, try to list what tables exist
    match conn.prepare("SELECT name, sql FROM sqlite_master WHERE type='table'") {
        Ok(mut stmt) => {
            let tables: Vec<(String, Option<String>)> = stmt
                .query_map([], |r| Ok((r.get::<_, String>(0).unwrap(), r.get::<_, Option<String>>(1).unwrap())))
                .unwrap()
                .filter_map(|r| r.ok())
                .collect();
            println!("Tables accessible: {}", tables.len());
            for (name, sql) in &tables {
                println!("  {} -> {}", name, sql.as_deref().unwrap_or("(no sql)").chars().take(60).collect::<String>());
            }
        }
        Err(e) => {
            println!("Cannot read sqlite_master: {}", e);
            println!("Will try direct table access...");
        }
    }

    // Try to access specific tables directly
    let test_tables = vec![
        "individuals",
        "individuals_keys",
        "individuals_cliopatria",
        "individuals_countries",
        "individuals_regions",
        "consolidate",
        "polities_cliopatria",
        "properties_definition",
        "occupations",
        "cities",
        "nationalities",
    ];

    for table in &test_tables {
        match conn.query_row(&format!("SELECT COUNT(*) FROM {}", table), [], |r| r.get::<_, i64>(0)) {
            Ok(count) => println!("  {} -> {} rows", table, count),
            Err(e) => println!("  {} -> ERROR: {}", table, e),
        }
    }
}
