/// Enhance individuals table:
/// 1. Add writing_language_name_en column (from individual_writing_languages)
/// 2. Reorder columns: birthdate_precision after birthdate, deathdate_precision after deathdate
/// 3. Fix writing_languages count and order by count DESC
///
/// Handles recovery: if individuals_backup exists from a previous failed run,
/// uses it directly instead of renaming.
use anyhow::Result;
use rusqlite::Connection;
use std::fs;
use std::io::Write;
use std::time::Instant;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const TASK_LOG: &str = "task.log";

fn log(msg: &str) {
    let now = chrono_now();
    let line = format!("[{}] {}", now, msg);
    println!("{}", line);
    let mut f = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(TASK_LOG)
        .unwrap();
    writeln!(f, "{}", line).unwrap();
}

fn chrono_now() -> String {
    let dur = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap();
    let secs = dur.as_secs();
    let hours = (secs % 86400) / 3600;
    let mins = (secs % 3600) / 60;
    let s = secs % 60;
    format!("{:02}:{:02}:{:02} UTC", hours, mins, s)
}

fn elapsed(start: Instant) -> String {
    let d = start.elapsed();
    let secs = d.as_secs();
    if secs < 60 {
        format!("{}s", secs)
    } else if secs < 3600 {
        format!("{}m {}s", secs / 60, secs % 60)
    } else {
        format!("{}h {}m {}s", secs / 3600, (secs % 3600) / 60, secs % 60)
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
    log("=== Step 12: Enhance individuals + fix writing_languages ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // --- Recovery: handle leftover backup tables ---
    if table_exists(&conn, "individuals_backup") {
        log("[12] RECOVERY: Found individuals_backup from previous failed run");
        let backup_count: i64 = conn.query_row(
            "SELECT COUNT(*) FROM individuals_backup",
            [],
            |r| r.get(0),
        )?;
        let current_count: i64 = conn.query_row(
            "SELECT COUNT(*) FROM individuals",
            [],
            |r| r.get(0),
        )?;
        log(&format!(
            "[12]   individuals: {} rows, individuals_backup: {} rows",
            current_count, backup_count
        ));

        if backup_count > current_count {
            log("[12]   Backup has more data, dropping empty individuals and restoring...");
            conn.execute_batch(
                "DROP TABLE individuals;
                 ALTER TABLE individuals_backup RENAME TO individuals;",
            )?;
            log("[12]   Restored individuals from backup");
        } else {
            log("[12]   Dropping stale backup...");
            conn.execute_batch("DROP TABLE individuals_backup;")?;
        }
    }

    // --- Part A: Aggregate writing languages per individual ---
    let step = Instant::now();
    log("[12] Part A: Aggregating writing languages per individual...");
    conn.execute_batch(
        "CREATE TEMP TABLE lang_agg AS
         SELECT wikidata_id, GROUP_CONCAT(language_name, ', ') AS langs
         FROM individual_writing_languages
         GROUP BY wikidata_id;",
    )?;
    let lang_count: i64 =
        conn.query_row("SELECT COUNT(*) FROM lang_agg", [], |r| r.get(0))?;
    log(&format!(
        "[12]   {} individuals with writing language data ({})",
        lang_count,
        elapsed(step)
    ));

    conn.execute_batch("CREATE INDEX idx_lang_agg_wid ON lang_agg(wikidata_id);")?;
    log(&format!("[12]   Temp table indexed ({})", elapsed(step)));

    // --- Part B: Restructure individuals table ---
    let step = Instant::now();
    let total: i64 = conn.query_row("SELECT COUNT(*) FROM individuals", [], |r| r.get(0))?;
    log(&format!(
        "[12] Part B: Restructuring individuals table ({} rows)...",
        total
    ));

    // Step B1: Rename
    conn.execute_batch("ALTER TABLE individuals RENAME TO individuals_backup;")?;
    log(&format!("[12]   Renamed to backup ({})", elapsed(step)));

    // Step B2: Create new table
    conn.execute_batch(
        "CREATE TABLE individuals (
             wikidata_id TEXT PRIMARY KEY,
             name_en TEXT,
             description_en TEXT,
             birthdate TEXT,
             birthdate_precision INTEGER,
             deathdate TEXT,
             deathdate_precision INTEGER,
             nationalities_en TEXT,
             birthcity_en TEXT,
             deathcity_en TEXT,
             occupations_en TEXT,
             sitelinks_count INTEGER DEFAULT 0,
             gender TEXT,
             identifiers_count INTEGER DEFAULT 0,
             writing_language_name_en TEXT
         );",
    )?;
    log(&format!("[12]   New table created ({})", elapsed(step)));

    // Step B3: Insert with LEFT JOIN
    log("[12]   Inserting 13M rows with LEFT JOIN for writing_language_name_en...");
    let insert_start = Instant::now();
    conn.execute_batch(
        "INSERT INTO individuals
         SELECT
             i.wikidata_id, i.name_en, i.description_en,
             i.birthdate, i.birthdate_precision,
             i.deathdate, i.deathdate_precision,
             i.nationalities_en, i.birthcity_en, i.deathcity_en,
             i.occupations_en, i.sitelinks_count, i.gender, i.identifiers_count,
             la.langs
         FROM individuals_backup i
         LEFT JOIN lang_agg la ON la.wikidata_id = i.wikidata_id;",
    )?;
    log(&format!("[12]   INSERT complete ({} for {} rows)", elapsed(insert_start), total));

    // Step B4: Drop backup
    conn.execute_batch("DROP TABLE individuals_backup;")?;
    log(&format!("[12]   Backup dropped ({})", elapsed(step)));

    // Step B5: Recreate indexes
    let idx_start = Instant::now();
    log("[12]   Creating indexes...");
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_name_en ON individuals(name_en);
         CREATE INDEX IF NOT EXISTS idx_birthcity_en ON individuals(birthcity_en);
         CREATE INDEX IF NOT EXISTS idx_sitelinks_count ON individuals(sitelinks_count);
         CREATE INDEX IF NOT EXISTS idx_birthdate_precision ON individuals(birthdate_precision);
         CREATE INDEX IF NOT EXISTS idx_deathdate_precision ON individuals(deathdate_precision);",
    )?;
    log(&format!("[12]   Indexes created ({})", elapsed(idx_start)));

    let verify: i64 = conn.query_row("SELECT COUNT(*) FROM individuals", [], |r| r.get(0))?;
    let with_lang: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals WHERE writing_language_name_en IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    log(&format!(
        "[12]   Result: {} rows, {} with writing_language_name_en",
        verify, with_lang
    ));

    let mut stmt = conn.prepare("PRAGMA table_info(individuals)")?;
    let cols: Vec<String> = stmt
        .query_map([], |r| r.get::<_, String>(1))?
        .filter_map(|r| r.ok())
        .collect();
    log(&format!("[12]   Columns: {}", cols.join(", ")));

    // --- Part C: Fix writing_languages count and reorder ---
    let step = Instant::now();
    log("[12] Part C: Updating writing_languages count...");
    conn.execute_batch(
        "UPDATE writing_languages SET count = COALESCE(
           (SELECT COUNT(*) FROM individual_writing_languages
            WHERE language_id = writing_languages.id), 0);",
    )?;

    let wl_nonzero: i64 = conn.query_row(
        "SELECT COUNT(*) FROM writing_languages WHERE count > 0",
        [],
        |r| r.get(0),
    )?;
    log(&format!(
        "[12]   {} languages with non-zero count ({})",
        wl_nonzero,
        elapsed(step)
    ));

    log("[12]   Reordering writing_languages by count DESC...");
    conn.execute_batch(
        "ALTER TABLE writing_languages RENAME TO writing_languages_backup;

         CREATE TABLE writing_languages (
             id TEXT PRIMARY KEY,
             name TEXT NOT NULL,
             count INTEGER DEFAULT 0
         );

         INSERT INTO writing_languages (id, name, count)
         SELECT id, name, count
         FROM writing_languages_backup
         ORDER BY count DESC;

         DROP TABLE writing_languages_backup;",
    )?;

    let wl_total: i64 =
        conn.query_row("SELECT COUNT(*) FROM writing_languages", [], |r| r.get(0))?;
    log(&format!(
        "[12]   Writing languages: {} total ({})",
        wl_total,
        elapsed(step)
    ));

    let mut stmt2 = conn.prepare("SELECT name, count FROM writing_languages LIMIT 5")?;
    let rows: Vec<(String, i64)> = stmt2
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
        .filter_map(|r| r.ok())
        .collect();
    for (name, count) in &rows {
        log(&format!("[12]     {} ({})", name, count));
    }

    log(&format!(
        "=== Step 12 complete (total: {}) ===",
        elapsed(total_start)
    ));
    Ok(())
}
