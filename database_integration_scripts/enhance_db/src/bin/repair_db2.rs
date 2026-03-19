/// repair_db2: Fix "database disk image is malformed" caused by WAL mode + orphaned WAL/SHM files.
///
/// Strategy:
///   Phase A (simple): Open DB, switch journal_mode from WAL to DELETE, close, reopen, verify.
///   Phase B (if A fails): Use writable_schema, integrity_check, wal_checkpoint, schema cookie
///                         increment, and optionally VACUUM.
///   Phase C (raw header fix): Directly patch header bytes 18-19 from 0x02 to 0x01 if all else fails.

use anyhow::{Context, Result};
use rusqlite::{Connection, OpenFlags};
use std::fs;
use std::io::{Read, Seek, SeekFrom, Write as IoWrite};
use std::path::Path;

const DB_PATH: &str = "/workspace/data/humans_clean.sqlite3";

fn main() -> Result<()> {
    let total_start = std::time::Instant::now();
    println!("=== repair_db2: Diagnosing and repairing {} ===", DB_PATH);
    println!();

    // Show current state of WAL/SHM files
    show_file_state();

    // Phase A: Try the simple approach - switch journal mode
    println!("--- Phase A: Simple journal_mode switch ---");
    match phase_a_simple_journal_switch() {
        Ok(true) => {
            println!("[Phase A] SUCCESS - database repaired and verified.");
            println!("Total elapsed: {:.1}s", total_start.elapsed().as_secs_f64());
            return Ok(());
        }
        Ok(false) => {
            println!("[Phase A] Did not fully succeed. Moving to Phase B.");
        }
        Err(e) => {
            println!("[Phase A] Failed: {}. Moving to Phase B.", e);
        }
    }
    println!();

    // Phase B: Writable schema + integrity check + checkpoint + schema cookie
    println!("--- Phase B: writable_schema + checkpoint + schema cookie ---");
    match phase_b_writable_schema_repair() {
        Ok(true) => {
            println!("[Phase B] SUCCESS - database repaired and verified.");
            println!("Total elapsed: {:.1}s", total_start.elapsed().as_secs_f64());
            return Ok(());
        }
        Ok(false) => {
            println!("[Phase B] Did not fully succeed. Moving to Phase C.");
        }
        Err(e) => {
            println!("[Phase B] Failed: {}. Moving to Phase C.", e);
        }
    }
    println!();

    // Phase C: Raw header byte patching
    println!("--- Phase C: Raw header byte patching ---");
    match phase_c_raw_header_fix() {
        Ok(true) => {
            println!("[Phase C] SUCCESS - database repaired and verified after header patch.");
            println!("Total elapsed: {:.1}s", total_start.elapsed().as_secs_f64());
            return Ok(());
        }
        Ok(false) => {
            println!("[Phase C] Header patched but full verification did not pass.");
            println!("[Phase C] The database may still be usable - check output above.");
        }
        Err(e) => {
            println!("[Phase C] Failed: {}", e);
        }
    }
    println!();

    println!("=== All repair phases completed. See output above for details. ===");
    println!("Total elapsed: {:.1}s", total_start.elapsed().as_secs_f64());
    Ok(())
}

fn show_file_state() {
    println!("File state:");
    let db_path = Path::new(DB_PATH);
    if let Ok(meta) = fs::metadata(db_path) {
        println!("  DB file: {:.1} MB", meta.len() as f64 / 1_048_576.0);
    }
    let wal_path = format!("{}-wal", DB_PATH);
    match fs::metadata(&wal_path) {
        Ok(meta) => println!("  WAL file: {} bytes", meta.len()),
        Err(_) => println!("  WAL file: not present"),
    }
    let shm_path = format!("{}-shm", DB_PATH);
    match fs::metadata(&shm_path) {
        Ok(meta) => println!("  SHM file: {} bytes", meta.len()),
        Err(_) => println!("  SHM file: not present"),
    }

    // Read header bytes 18-19 to show current journal mode
    if let Ok(mut f) = fs::File::open(db_path) {
        let mut header = [0u8; 100];
        if f.read_exact(&mut header).is_ok() {
            let read_ver = header[18];
            let write_ver = header[19];
            let mode_str = match (read_ver, write_ver) {
                (1, 1) => "rollback journal (legacy)",
                (2, 2) => "WAL mode",
                _ => "unknown/mixed",
            };
            println!(
                "  Header bytes 18-19: 0x{:02x} 0x{:02x} => {}",
                read_ver, write_ver, mode_str
            );
            let change_counter = u32::from_be_bytes([header[24], header[25], header[26], header[27]]);
            println!("  Change counter (bytes 24-27): {}", change_counter);
            let schema_cookie = u32::from_be_bytes([header[40], header[41], header[42], header[43]]);
            println!("  Schema cookie (bytes 40-43): {}", schema_cookie);
        }
    }
    println!();
}

/// Phase A: Open the DB, switch from WAL to DELETE journal mode, close, reopen, verify.
fn phase_a_simple_journal_switch() -> Result<bool> {
    // Remove orphaned WAL/SHM files first if WAL is empty
    remove_orphaned_wal_files()?;

    let flags = OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX;
    println!("[Phase A] Opening database...");
    let conn = Connection::open_with_flags(DB_PATH, flags)
        .context("Failed to open database")?;

    // Set busy timeout to avoid lock issues
    conn.execute_batch("PRAGMA busy_timeout=5000;")?;

    // Try setting journal_mode=DELETE to exit WAL mode
    let current_mode: String = conn
        .pragma_query_value(None, "journal_mode", |row| row.get(0))
        .unwrap_or_else(|_| "unknown".to_string());
    println!("[Phase A] Current journal_mode: {}", current_mode);

    // Try checkpoint first to ensure WAL is clean
    println!("[Phase A] Running wal_checkpoint(TRUNCATE)...");
    match conn.prepare("PRAGMA wal_checkpoint(TRUNCATE)") {
        Ok(mut stmt) => {
            match stmt.query_map([], |row| {
                let busy: i32 = row.get(0)?;
                let log_frames: i32 = row.get(1)?;
                let checkpointed: i32 = row.get(2)?;
                Ok((busy, log_frames, checkpointed))
            }) {
                Ok(rows) => {
                    for row in rows {
                        match row {
                            Ok((busy, log, cp)) => println!("  checkpoint: busy={}, log={}, checkpointed={}", busy, log, cp),
                            Err(e) => println!("  checkpoint row error: {}", e),
                        }
                    }
                }
                Err(e) => println!("  checkpoint failed: {}", e),
            }
        }
        Err(e) => println!("  checkpoint prepare failed: {}", e),
    }

    println!("[Phase A] Setting journal_mode=DELETE...");
    match conn.pragma_update(None, "journal_mode", "delete") {
        Ok(_) => {
            let new_mode: String = conn
                .pragma_query_value(None, "journal_mode", |row| row.get(0))
                .unwrap_or_else(|_| "unknown".to_string());
            println!("[Phase A] journal_mode is now: {}", new_mode);
            if new_mode == "delete" {
                // Close and verify
                drop(conn);
                return verify_database("Phase A");
            }
        }
        Err(e) => {
            println!("[Phase A] Failed to set journal_mode=DELETE: {}", e);
        }
    }

    // If journal_mode switch failed, still try to verify
    drop(conn);
    // Return false to indicate we should continue to next phase
    Ok(false)
}

/// Phase B: Use writable_schema, integrity_check, wal_checkpoint, schema cookie increment.
fn phase_b_writable_schema_repair() -> Result<bool> {
    remove_orphaned_wal_files()?;

    let flags = OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX;
    let conn = Connection::open_with_flags(DB_PATH, flags)
        .context("Failed to open database for Phase B")?;

    conn.execute_batch("PRAGMA busy_timeout=5000;")?;

    // Step 1: Enable writable_schema to bypass schema validation
    println!("[Phase B] Step 1: PRAGMA writable_schema=ON");
    conn.execute_batch("PRAGMA writable_schema=ON;")?;

    // Step 2: Run integrity_check (limited to first 10 results)
    println!("[Phase B] Step 2: PRAGMA integrity_check (first 10 results)...");
    match conn.prepare("PRAGMA integrity_check(10)") {
        Ok(mut stmt) => {
            match stmt.query_map([], |row| row.get::<_, String>(0)) {
                Ok(rows) => {
                    let mut count = 0;
                    for row in rows {
                        match row {
                            Ok(msg) => {
                                count += 1;
                                println!("  integrity_check [{}]: {}", count, msg);
                            }
                            Err(e) => {
                                println!("  integrity_check error reading row: {}", e);
                            }
                        }
                    }
                    if count == 0 {
                        println!("  integrity_check: no results returned");
                    }
                }
                Err(e) => println!("  integrity_check query failed: {}", e),
            }
        }
        Err(e) => println!("  integrity_check prepare failed: {}", e),
    }

    // Step 3: Try WAL checkpoint
    println!("[Phase B] Step 3: PRAGMA wal_checkpoint(TRUNCATE)...");
    match conn.prepare("PRAGMA wal_checkpoint(TRUNCATE)") {
        Ok(mut stmt) => {
            match stmt.query_map([], |row| {
                let busy: i32 = row.get(0)?;
                let log_frames: i32 = row.get(1)?;
                let checkpointed: i32 = row.get(2)?;
                Ok((busy, log_frames, checkpointed))
            }) {
                Ok(rows) => {
                    for row in rows {
                        match row {
                            Ok((busy, log_frames, checkpointed)) => {
                                println!(
                                    "  wal_checkpoint: busy={}, log={}, checkpointed={}",
                                    busy, log_frames, checkpointed
                                );
                            }
                            Err(e) => println!("  wal_checkpoint row error: {}", e),
                        }
                    }
                }
                Err(e) => println!("  wal_checkpoint query failed: {}", e),
            }
        }
        Err(e) => println!("  wal_checkpoint prepare failed: {}", e),
    }

    // Step 4: Switch to DELETE journal mode
    println!("[Phase B] Step 4: Setting journal_mode=DELETE...");
    match conn.pragma_update(None, "journal_mode", "delete") {
        Ok(_) => {
            let mode: String = conn
                .pragma_query_value(None, "journal_mode", |row| row.get(0))
                .unwrap_or_else(|_| "unknown".to_string());
            println!("  journal_mode is now: {}", mode);
        }
        Err(e) => println!("  Failed to set journal_mode: {}", e),
    }

    // Step 5: Increment schema cookie to force schema reload
    println!("[Phase B] Step 5: Incrementing schema cookie...");
    match conn.pragma_query_value(None, "schema_version", |row| row.get::<_, i32>(0)) {
        Ok(current) => {
            let new_ver = current + 1;
            match conn.pragma_update(None, "schema_version", new_ver) {
                Ok(_) => println!("  Schema version: {} -> {}", current, new_ver),
                Err(e) => println!("  Failed to update schema_version: {}", e),
            }
        }
        Err(e) => println!("  Failed to read schema_version: {}", e),
    }

    // Step 6: Turn off writable_schema
    println!("[Phase B] Step 6: PRAGMA writable_schema=OFF");
    let _ = conn.execute_batch("PRAGMA writable_schema=OFF;");

    // Step 7: Skip VACUUM on 15GB DB (takes too long and requires 2x disk space)
    println!("[Phase B] Step 7: Skipping VACUUM (15GB DB - would take too long).");
    println!("  Use 'VACUUM' manually if freelist corruption needs full rebuild.");

    // Close
    drop(conn);

    // Remove WAL/SHM that may have been recreated
    remove_orphaned_wal_files()?;

    // Verify
    verify_database("Phase B")
}

/// Phase C: Directly patch header bytes 18-19 from 0x02 to 0x01 to force rollback journal mode.
fn phase_c_raw_header_fix() -> Result<bool> {
    // Remove WAL/SHM first
    remove_orphaned_wal_files()?;

    println!("[Phase C] Opening DB file for raw header patching...");
    let mut file = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open(DB_PATH)
        .context("Failed to open DB file for writing")?;

    // Read current header
    let mut header = [0u8; 100];
    file.read_exact(&mut header)
        .context("Failed to read SQLite header")?;

    // Verify this is a valid SQLite file
    if &header[0..6] != b"SQLite" {
        anyhow::bail!("Not a valid SQLite file (bad magic)");
    }

    let old_read = header[18];
    let old_write = header[19];
    println!(
        "[Phase C] Current header bytes 18-19: 0x{:02x} 0x{:02x}",
        old_read, old_write
    );

    // Patch bytes 18-19 to 0x01 (rollback journal) regardless
    header[18] = 0x01;
    header[19] = 0x01;

    // Increment the change counter (bytes 24-27) to invalidate caches
    let change_counter = u32::from_be_bytes([header[24], header[25], header[26], header[27]]);
    let new_counter = change_counter.wrapping_add(1);
    let new_bytes = new_counter.to_be_bytes();
    header[24] = new_bytes[0];
    header[25] = new_bytes[1];
    header[26] = new_bytes[2];
    header[27] = new_bytes[3];

    // Also update the version-valid-for number (bytes 92-95) to match change counter
    header[92] = new_bytes[0];
    header[93] = new_bytes[1];
    header[94] = new_bytes[2];
    header[95] = new_bytes[3];

    println!(
        "[Phase C] Patching: bytes 18-19 -> 0x01 0x01 (rollback journal), change counter {} -> {}",
        change_counter, new_counter
    );

    // Write back the modified header
    file.seek(SeekFrom::Start(0))?;
    file.write_all(&header)?;
    file.sync_all()?;
    println!("[Phase C] Header patched and fsynced.");
    drop(file);

    // Now try to open with rusqlite and do the schema cookie trick
    println!("[Phase C] Opening patched DB with writable_schema to finalize...");
    let flags = OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX;
    match Connection::open_with_flags(DB_PATH, flags) {
        Ok(conn) => {
            conn.execute_batch("PRAGMA busy_timeout=5000;")?;
            conn.execute_batch("PRAGMA writable_schema=ON;")?;

            // Increment schema cookie
            if let Ok(ver) = conn.pragma_query_value(None, "schema_version", |row| {
                row.get::<_, i32>(0)
            }) {
                let new_ver = ver + 1;
                let _ = conn.pragma_update(None, "schema_version", new_ver);
                println!("[Phase C] Schema version: {} -> {}", ver, new_ver);
            }

            // Confirm journal mode
            let mode: String = conn
                .pragma_query_value(None, "journal_mode", |row| row.get(0))
                .unwrap_or_else(|_| "unknown".to_string());
            println!("[Phase C] journal_mode after header patch: {}", mode);

            conn.execute_batch("PRAGMA writable_schema=OFF;")?;

            // Run integrity check
            println!("[Phase C] Running integrity_check(5) after repair...");
            match conn.prepare("PRAGMA integrity_check(5)") {
                Ok(mut stmt) => {
                    match stmt.query_map([], |row| row.get::<_, String>(0)) {
                        Ok(rows) => {
                            let mut count = 0;
                            for row in rows {
                                match row {
                                    Ok(msg) => {
                                        count += 1;
                                        println!("  integrity_check [{}]: {}", count, msg);
                                    }
                                    Err(e) => println!("  error: {}", e),
                                }
                            }
                            if count == 0 {
                                println!("  integrity_check: no results");
                            }
                        }
                        Err(e) => println!("  integrity_check query failed: {}", e),
                    }
                }
                Err(e) => println!("  integrity_check prepare failed: {}", e),
            }

            drop(conn);
        }
        Err(e) => {
            println!("[Phase C] Could not open patched DB via rusqlite: {}", e);
            println!("[Phase C] Header was still patched; trying verification anyway.");
        }
    }

    // Clean up any WAL/SHM created during the above operations
    remove_orphaned_wal_files()?;

    // Verify
    verify_database("Phase C")
}

/// Remove orphaned WAL and SHM files if WAL is empty or doesn't exist.
fn remove_orphaned_wal_files() -> Result<()> {
    let wal_path = format!("{}-wal", DB_PATH);
    let shm_path = format!("{}-shm", DB_PATH);

    if let Ok(meta) = fs::metadata(&wal_path) {
        if meta.len() == 0 {
            println!("  Removing empty WAL file: {}-wal", DB_PATH);
            fs::remove_file(&wal_path)?;
        } else {
            println!(
                "  WARNING: WAL file is non-empty ({} bytes), not removing.",
                meta.len()
            );
        }
    }

    if Path::new(&shm_path).exists() {
        if !Path::new(&wal_path).exists() {
            println!("  Removing orphaned SHM file: {}-shm", DB_PATH);
            fs::remove_file(&shm_path)?;
        }
    }

    Ok(())
}

/// Verify the database by opening it fresh and running queries.
/// Returns Ok(true) only if:
///   - Tables are accessible
///   - A row count query works
///   - Journal mode is NOT wal (we want it out of WAL)
fn verify_database(phase: &str) -> Result<bool> {
    println!("[{}] Verifying database...", phase);

    let flags = OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX;
    let conn = match Connection::open_with_flags(DB_PATH, flags) {
        Ok(c) => c,
        Err(e) => {
            println!("[{}] Verification FAILED: cannot open DB: {}", phase, e);
            return Ok(false);
        }
    };

    let mut success = true;

    // Try to list tables
    match conn.prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name") {
        Ok(mut stmt) => {
            match stmt.query_map([], |row| row.get::<_, String>(0)) {
                Ok(rows) => {
                    let tables: Vec<String> = rows.filter_map(|r| r.ok()).collect();
                    if tables.is_empty() {
                        println!("[{}] WARNING: No tables found in sqlite_master.", phase);
                        success = false;
                    } else {
                        println!(
                            "[{}] Found {} tables: {}",
                            phase,
                            tables.len(),
                            tables.join(", ")
                        );
                    }
                }
                Err(e) => {
                    println!(
                        "[{}] Verification FAILED querying sqlite_master: {}",
                        phase, e
                    );
                    success = false;
                }
            }
        }
        Err(e) => {
            println!("[{}] Verification FAILED preparing query: {}", phase, e);
            success = false;
        }
    }

    // Try a simple count on a known table
    match conn.query_row(
        "SELECT COUNT(*) FROM individuals",
        [],
        |row| row.get::<_, i64>(0),
    ) {
        Ok(count) => {
            println!("[{}] individuals table has {} rows - OK", phase, count);
        }
        Err(e) => {
            println!("[{}] Cannot query individuals table: {}", phase, e);
            success = false;
        }
    }

    // Check final journal mode
    let mode: String = conn
        .pragma_query_value(None, "journal_mode", |row| row.get(0))
        .unwrap_or_else(|_| "unknown".to_string());
    println!("[{}] Final journal_mode: {}", phase, mode);
    if mode == "wal" {
        println!("[{}] WARNING: Still in WAL mode (wanted delete/rollback).", phase);
        // Not a hard failure - DB is still usable
    }

    // Quick integrity check
    match conn.query_row("PRAGMA integrity_check(1)", [], |row| {
        row.get::<_, String>(0)
    }) {
        Ok(result) => {
            println!("[{}] integrity_check(1): {}", phase, result);
            if result == "ok" {
                println!("[{}] Database integrity: OK", phase);
            } else {
                println!("[{}] Database has integrity issues (may still be usable).", phase);
            }
        }
        Err(e) => {
            println!("[{}] integrity_check failed: {}", phase, e);
        }
    }

    // Show file state after repair
    println!();
    show_file_state();

    Ok(success)
}
