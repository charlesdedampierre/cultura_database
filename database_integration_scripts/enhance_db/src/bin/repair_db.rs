/// Focused repair: rebuild corrupted identifiers table, fix sitelinks, create indexes.
/// Uses rowid-based batching instead of OFFSET for efficiency.
use anyhow::Result;
use rusqlite::Connection;
use std::fs;
use std::io::Write;
use std::time::Instant;

const DB: &str = "/workspace/data/humans_clean.sqlite3";

fn log(msg: &str) {
    let dur = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap();
    let secs = dur.as_secs();
    let ts = format!(
        "{:02}:{:02}:{:02}",
        (secs % 86400) / 3600,
        (secs % 3600) / 60,
        secs % 60
    );
    let line = format!("[{}] {}", ts, msg);
    println!("{}", line);
    if let Ok(mut f) = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open("/workspace/task.log")
    {
        let _ = writeln!(f, "{}", line);
    }
}

fn elapsed(start: Instant) -> String {
    let s = start.elapsed().as_secs();
    if s < 60 {
        format!("{}s", s)
    } else if s < 3600 {
        format!("{}m {}s", s / 60, s % 60)
    } else {
        format!("{}h {}m {}s", s / 3600, (s % 3600) / 60, s % 60)
    }
}

fn table_exists(conn: &Connection, name: &str) -> bool {
    conn.query_row(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?1",
        [name],
        |r| r.get::<_, i64>(0),
    )
    .unwrap_or(0)
        > 0
}

fn main() -> Result<()> {
    let total_start = Instant::now();
    log("=== REPAIR: Fixing database issues ===");

    let conn = Connection::open(DB)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000; PRAGMA busy_timeout=30000;",
    )?;

    // --- Phase 1: Fix sitelinks if needed ---
    log("[REPAIR] Phase 1: Checking sitelinks...");
    if table_exists(&conn, "sitelinks_backup") {
        let sitelinks_count: i64 = conn
            .query_row("SELECT COUNT(*) FROM sitelinks", [], |r| r.get(0))
            .unwrap_or(0);
        let backup_count: i64 = conn
            .query_row("SELECT COUNT(*) FROM sitelinks_backup", [], |r| r.get(0))
            .unwrap_or(0);
        log(&format!(
            "[REPAIR]   sitelinks: {}, sitelinks_backup: {}",
            sitelinks_count, backup_count
        ));
        if backup_count > sitelinks_count {
            conn.execute_batch("DROP TABLE IF EXISTS sitelinks;")?;
            conn.execute_batch("ALTER TABLE sitelinks_backup RENAME TO sitelinks;")?;
            log(&format!("[REPAIR]   Restored sitelinks: {} rows", backup_count));
        } else {
            conn.execute_batch("DROP TABLE IF EXISTS sitelinks_backup;")?;
            log("[REPAIR]   Dropped stale sitelinks_backup");
        }
    } else {
        let count: i64 = conn.query_row("SELECT COUNT(*) FROM sitelinks", [], |r| r.get(0)).unwrap_or(0);
        log(&format!("[REPAIR]   Sitelinks OK: {} rows", count));
    }

    // Drop any leftover backup tables
    for t in &["individuals_backup"] {
        if table_exists(&conn, t) {
            conn.execute_batch(&format!("DROP TABLE IF EXISTS \"{}\";", t))?;
            log(&format!("[REPAIR]   Dropped leftover {}", t));
        }
    }

    // --- Phase 2: Rebuild identifiers if corrupted ---
    log("[REPAIR] Phase 2: Checking identifiers...");
    let identifiers_ok = conn
        .query_row("SELECT COUNT(*) FROM identifiers", [], |r| r.get::<_, i64>(0))
        .is_ok();

    if identifiers_ok {
        let count: i64 = conn.query_row("SELECT COUNT(*) FROM identifiers", [], |r| r.get(0))?;
        log(&format!("[REPAIR]   Identifiers OK: {} rows", count));
    } else {
        log("[REPAIR]   Identifiers corrupted, rebuilding...");
        let start = Instant::now();

        // Drop partial rebuild if it exists
        conn.execute_batch("DROP TABLE IF EXISTS identifiers_new;")?;

        // Create fresh target table
        conn.execute_batch(
            "CREATE TABLE identifiers_new (
                 wikidata_id TEXT,
                 individual_name TEXT,
                 property_id TEXT,
                 identifier_name TEXT,
                 value TEXT,
                 url TEXT,
                 PRIMARY KEY (wikidata_id, property_id, value)
             );",
        )?;

        // Use rowid-based batching for O(n) instead of O(n^2)
        let batch_size: i64 = 500_000;
        let mut last_rowid: i64 = 0;
        let mut total_copied: i64 = 0;

        loop {
            let result = conn.execute(
                "INSERT OR IGNORE INTO identifiers_new
                 SELECT wikidata_id, individual_name, property_id, identifier_name, value, url
                 FROM identifiers
                 WHERE rowid > ?1
                 ORDER BY rowid
                 LIMIT ?2",
                rusqlite::params![last_rowid, batch_size],
            );

            match result {
                Ok(n) if n == 0 => {
                    log(&format!(
                        "[REPAIR]     Done copying. Total: {} rows ({})",
                        total_copied,
                        elapsed(start)
                    ));
                    break;
                }
                Ok(n) => {
                    total_copied += n as i64;
                    // Get the max rowid we just inserted
                    last_rowid = conn
                        .query_row(
                            &format!(
                                "SELECT MAX(rowid) FROM identifiers WHERE rowid > {} ORDER BY rowid LIMIT {}",
                                last_rowid, batch_size
                            ),
                            [],
                            |r| r.get::<_, i64>(0),
                        )
                        .unwrap_or(last_rowid + batch_size);
                    log(&format!(
                        "[REPAIR]     Copied {} rows so far (rowid > {}) ({})",
                        total_copied, last_rowid, elapsed(start)
                    ));
                }
                Err(e) => {
                    log(&format!(
                        "[REPAIR]     Error at rowid {}: {}. Skipping batch.",
                        last_rowid, e
                    ));
                    // Skip this batch and try the next range
                    last_rowid += batch_size;
                    // Check if we're past the end
                    let remaining = conn
                        .query_row(
                            "SELECT COUNT(*) FROM identifiers WHERE rowid > ?1 LIMIT 1",
                            [last_rowid],
                            |r| r.get::<_, i64>(0),
                        )
                        .unwrap_or(0);
                    if remaining == 0 {
                        log(&format!(
                            "[REPAIR]     No more rows. Total copied: {} ({})",
                            total_copied,
                            elapsed(start)
                        ));
                        break;
                    }
                }
            }
        }

        // Swap tables
        log("[REPAIR]   Swapping identifiers tables...");
        conn.execute_batch("DROP TABLE identifiers;")?;
        conn.execute_batch("ALTER TABLE identifiers_new RENAME TO identifiers;")?;

        let verify: i64 =
            conn.query_row("SELECT COUNT(*) FROM identifiers", [], |r| r.get(0))?;
        log(&format!(
            "[REPAIR]   Identifiers rebuilt: {} rows ({})",
            verify,
            elapsed(start)
        ));

        // Create indexes
        log("[REPAIR]   Creating identifiers indexes...");
        let idx_start = Instant::now();
        conn.execute_batch(
            "CREATE INDEX IF NOT EXISTS idx_identifiers_wikidata ON identifiers(wikidata_id);
             CREATE INDEX IF NOT EXISTS idx_identifiers_property ON identifiers(property_id);
             CREATE INDEX IF NOT EXISTS idx_identifiers_name ON identifiers(individual_name);",
        )?;
        log(&format!(
            "[REPAIR]   Identifiers indexes done ({})",
            elapsed(idx_start)
        ));
    }

    // --- Phase 3: Create indexes on individuals ---
    log("[REPAIR] Phase 3: Creating individuals indexes...");
    let idx_start = Instant::now();
    for sql in &[
        "CREATE INDEX IF NOT EXISTS idx_name_en ON individuals(name_en)",
        "CREATE INDEX IF NOT EXISTS idx_birthcity_en ON individuals(birthcity_en)",
        "CREATE INDEX IF NOT EXISTS idx_sitelinks_count ON individuals(sitelinks_count)",
        "CREATE INDEX IF NOT EXISTS idx_birthdate_precision ON individuals(birthdate_precision)",
        "CREATE INDEX IF NOT EXISTS idx_deathdate_precision ON individuals(deathdate_precision)",
    ] {
        match conn.execute_batch(sql) {
            Ok(_) => {}
            Err(e) => log(&format!("[REPAIR]   Index error: {}", e)),
        }
    }
    log(&format!(
        "[REPAIR]   Individuals indexes done ({})",
        elapsed(idx_start)
    ));

    // --- Final summary ---
    log(&format!("[REPAIR] === Final Summary (total: {}) ===", elapsed(total_start)));
    for t in &[
        "individuals", "sitelinks", "identifiers", "cities",
        "modern_country", "writing_languages", "properties_definition",
        "occupations", "nationalities",
    ] {
        match conn.query_row(
            &format!("SELECT COUNT(*) FROM \"{}\"", t),
            [],
            |r| r.get::<_, i64>(0),
        ) {
            Ok(count) => {
                let mut s = conn.prepare(&format!("PRAGMA table_info(\"{}\")", t)).unwrap();
                let cols: Vec<String> = s
                    .query_map([], |r| r.get::<_, String>(1))
                    .unwrap()
                    .filter_map(|r| r.ok())
                    .collect();
                log(&format!("  {}: {} rows | {}", t, count, cols.join(", ")));
            }
            Err(e) => log(&format!("  {}: ERROR - {}", t, e)),
        }
    }

    log("=== REPAIR complete ===");
    Ok(())
}
