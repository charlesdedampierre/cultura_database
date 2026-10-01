use rusqlite::Connection;

fn main() {
    let conn = Connection::open("/workspace/data/humans_clean.sqlite3").unwrap();
    conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA cache_size=-500000;").unwrap();
    println!("Database opened successfully");

    // List tables
    {
        let mut s = conn.prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").unwrap();
        let tables: Vec<String> = s.query_map([], |r| r.get(0)).unwrap().filter_map(|r| r.ok()).collect();
        println!("Tables: {:?}", tables);
    }

    // Check key tables
    for t in &["individuals", "individuals_backup", "sitelinks", "identifiers", "cities"] {
        match conn.query_row(&format!("SELECT COUNT(*) FROM \"{}\"", t), [], |r| r.get::<_, i64>(0)) {
            Ok(count) => println!("{}: {} rows", t, count),
            Err(e) => println!("{}: {}", t, e),
        }
    }

    // Check individuals columns
    {
        let mut s = conn.prepare("PRAGMA table_info(individuals)").unwrap();
        let cols: Vec<String> = s.query_map([], |r| r.get::<_, String>(1)).unwrap().filter_map(|r| r.ok()).collect();
        println!("individuals columns: {:?}", cols);
    }

    // Try to drop backup and create indexes
    println!("\nAttempting cleanup...");
    match conn.execute_batch("DROP TABLE IF EXISTS individuals_backup") {
        Ok(_) => println!("Dropped individuals_backup"),
        Err(e) => println!("Drop failed: {}", e),
    }

    match conn.query_row("SELECT COUNT(*) FROM individuals WHERE writing_language_name_en IS NOT NULL", [], |r| r.get::<_, i64>(0)) {
        Ok(c) => println!("With writing_language: {}", c),
        Err(e) => println!("Query failed: {}", e),
    }
}
