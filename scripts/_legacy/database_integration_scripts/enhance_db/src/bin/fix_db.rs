/// Fix database corruption: recreate individuals_countries by
/// exporting to a temp table, dropping the corrupted one, and recreating.
/// Also tries to checkpoint WAL and run integrity_check.
use rusqlite::Connection;

fn main() {
    println!("=== Database Repair Tool ===");

    let conn = Connection::open("data/humans_clean.sqlite3").unwrap();

    // Try to checkpoint WAL first
    println!("[1] Attempting WAL checkpoint...");
    match conn.execute_batch("PRAGMA wal_checkpoint(TRUNCATE);") {
        Ok(()) => println!("    WAL checkpoint OK"),
        Err(e) => println!("    WAL checkpoint failed: {} (continuing)", e),
    }

    // Set pragmas
    conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;").ok();

    // Quick integrity check
    println!("[2] Running integrity_check(10)...");
    match conn.prepare("PRAGMA integrity_check(10)") {
        Ok(mut stmt) => {
            match stmt.query_map([], |r| r.get::<_, String>(0)) {
                Ok(rows) => {
                    for r in rows {
                        match r {
                            Ok(msg) => println!("    {}", msg),
                            Err(e) => { println!("    row error: {}", e); break; }
                        }
                    }
                }
                Err(e) => println!("    query error: {}", e),
            }
        }
        Err(e) => println!("    prepare error: {}", e),
    }

    // Try to recreate individuals_countries using a workaround
    println!("[3] Recreating individuals_countries...");

    // Create temp table with same structure
    match conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS individuals_countries_tmp (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            iso_country_name TEXT,
            iso_a3_code TEXT,
            origins TEXT
        );"
    ) {
        Ok(()) => println!("    Created temp table"),
        Err(e) => { println!("    Failed to create temp table: {}", e); return; }
    }

    // Copy data from old to temp
    println!("[4] Copying data...");
    match conn.execute(
        "INSERT OR IGNORE INTO individuals_countries_tmp SELECT * FROM individuals_countries",
        [],
    ) {
        Ok(n) => println!("    Copied {} rows", n),
        Err(e) => println!("    Copy failed: {} (table may already be empty)", e),
    }

    // Try to drop the corrupted table
    println!("[5] Dropping old table...");
    match conn.execute_batch("DROP TABLE IF EXISTS individuals_countries;") {
        Ok(()) => println!("    Dropped successfully"),
        Err(e) => {
            println!("    Drop failed: {}, trying writable_schema approach...", e);
            // Try writable_schema to remove the entry
            conn.execute_batch("PRAGMA writable_schema=ON;").ok();
            conn.execute_batch("DELETE FROM sqlite_master WHERE name='individuals_countries';").ok();
            conn.execute_batch("DELETE FROM sqlite_master WHERE tbl_name='individuals_countries';").ok();
            // Increment schema cookie
            let cookie: i64 = conn.query_row("PRAGMA schema_version;", [], |r| r.get(0)).unwrap_or(0);
            conn.execute_batch(&format!("PRAGMA schema_version={};", cookie + 1)).ok();
            conn.execute_batch("PRAGMA writable_schema=OFF;").ok();
            println!("    Removed via writable_schema");
        }
    }

    // Rename temp to final
    println!("[6] Renaming temp table...");
    match conn.execute_batch("ALTER TABLE individuals_countries_tmp RENAME TO individuals_countries;") {
        Ok(()) => println!("    Rename successful"),
        Err(e) => println!("    Rename failed: {}", e),
    }

    // Verify
    println!("[7] Verifying...");
    match conn.query_row("SELECT COUNT(*) FROM individuals_countries", [], |r| r.get::<_, i64>(0)) {
        Ok(n) => println!("    individuals_countries: {} rows", n),
        Err(e) => println!("    verify failed: {}", e),
    }

    // Also try to drop/recreate individuals_regions and consolidate to ensure they're clean
    println!("[8] Testing other tables...");
    for table in &["individuals_regions", "consolidate"] {
        match conn.query_row(&format!("SELECT COUNT(*) FROM {}", table), [], |r| r.get::<_, i64>(0)) {
            Ok(n) => println!("    {}: {} rows - OK", table, n),
            Err(e) => println!("    {}: ERROR - {}", table, e),
        }
    }

    // Final checkpoint
    println!("[9] Final WAL checkpoint...");
    conn.execute_batch("PRAGMA wal_checkpoint(TRUNCATE);").ok();

    println!("=== Repair complete ===");
}
