/// Reorder all tables that have a 'count' column by count DESC.
/// SQLite doesn't store row order, so we recreate tables with ordered data.
/// Also adds English Wikipedia sitelinks to the cities table.
use anyhow::Result;
use rusqlite::Connection;
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

fn reorder_table(conn: &Connection, table: &str) -> Result<()> {
    log(&format!("[DB] Reordering {} by count DESC...", table));

    let backup = format!("{}_old", table);

    // Get the CREATE TABLE statement
    let create_sql: String = conn.query_row(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?1",
        [table],
        |row| row.get(0),
    )?;

    // Get column names
    let mut col_stmt = conn.prepare(&format!("PRAGMA table_info({})", table))?;
    let columns: Vec<String> = col_stmt
        .query_map([], |row| row.get::<_, String>(1))?
        .filter_map(|r| r.ok())
        .collect();
    let col_list = columns.join(", ");

    // Rename original
    conn.execute_batch(&format!("ALTER TABLE {} RENAME TO {};", table, backup))?;

    // Create new table with same schema
    conn.execute_batch(&create_sql)?;

    // Insert data ordered by count DESC
    conn.execute_batch(&format!(
        "INSERT INTO {} ({}) SELECT {} FROM {} ORDER BY count DESC;",
        table, col_list, col_list, backup
    ))?;

    // Drop backup
    conn.execute_batch(&format!("DROP TABLE {};", backup))?;

    let count: i64 = conn.query_row(&format!("SELECT COUNT(*) FROM {}", table), [], |row| row.get(0))?;
    log(&format!("[DB] {} reordered: {} rows", table, count));

    Ok(())
}

fn main() -> Result<()> {
    log("[DB] 09: Reordering tables by count and adding city sitelinks...");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;")?;

    // Add en_wikipedia_url to cities if not exists
    let city_cols: Vec<String> = conn
        .prepare("PRAGMA table_info(cities)")?
        .query_map([], |row| row.get::<_, String>(1))?
        .filter_map(|r| r.ok())
        .collect();

    if !city_cols.contains(&"en_wikipedia_url".to_string()) {
        conn.execute_batch("ALTER TABLE cities ADD COLUMN en_wikipedia_url TEXT;")?;
        log("[DB] Added en_wikipedia_url column to cities");
    }

    // Populate city sitelinks from the sitelinks table
    log("[DB] Populating city English Wikipedia sitelinks from sitelinks table...");
    // Cities don't have direct sitelinks in our data since sitelinks are for individuals.
    // Instead, we construct the Wikipedia URL from the city name.
    // Format: https://en.wikipedia.org/wiki/{name_en with spaces replaced by underscores}
    conn.execute(
        "UPDATE cities SET en_wikipedia_url = 'https://en.wikipedia.org/wiki/' || REPLACE(name_en, ' ', '_')
         WHERE name_en IS NOT NULL AND name_en != '' AND en_wikipedia_url IS NULL",
        [],
    )?;

    let cities_with_url: i64 = conn.query_row(
        "SELECT COUNT(*) FROM cities WHERE en_wikipedia_url IS NOT NULL",
        [],
        |row| row.get(0),
    )?;
    log(&format!("[DB] Cities with en_wikipedia_url: {}", cities_with_url));

    // Reorder all tables with count columns
    let tables_with_count = vec![
        "occupations",
        "nationalities",
        "cities",
        "identifier_types",
        "modern_country",
        "writing_languages",
    ];

    for table in &tables_with_count {
        // Check if table exists and has count column
        let has_count: bool = conn
            .prepare(&format!("PRAGMA table_info({})", table))
            .map(|mut stmt| {
                stmt.query_map([], |row| row.get::<_, String>(1))
                    .ok()
                    .map(|rows| rows.filter_map(|r| r.ok()).any(|c| c == "count"))
                    .unwrap_or(false)
            })
            .unwrap_or(false);

        if has_count {
            if let Err(e) = reorder_table(&conn, table) {
                log(&format!("[DB] Warning: could not reorder {}: {}", table, e));
            }
        } else {
            log(&format!("[DB] Skipping {} (no count column or table missing)", table));
        }
    }

    // Verify the ordering
    for table in &tables_with_count {
        let check: Result<Vec<(String, i64)>, _> = conn
            .prepare(&format!("SELECT COALESCE(name_en, name, id, ''), count FROM {} LIMIT 5", table))
            .and_then(|mut stmt| {
                let rows = stmt
                    .query_map([], |row| {
                        Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?))
                    })?
                    .filter_map(|r| r.ok())
                    .collect::<Vec<_>>();
                Ok(rows)
            });
        match check {
            Ok(rows) => {
                log(&format!("[DB] Top entries in {}:", table));
                for (name, count) in &rows {
                    log(&format!("  {} ({})", name, count));
                }
            }
            Err(_) => {}
        }
    }

    log("[DB] 09: Done. All tables ordered by count DESC.");
    Ok(())
}
