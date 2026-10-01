/// Add a `number_of_works` column to `individuals` and populate it from the
/// `works` table.
///
/// number_of_works = COUNT(DISTINCT work_id) per individual_id
/// (a work counted under multiple roles, e.g. director + screenwriter, is
///  counted once, matching the intuitive "how many distinct works" meaning).
///
/// Individuals with no entries in `works` get 0.
use anyhow::Result;
use rusqlite::Connection;
use std::fs;
use std::io::Write;
use std::time::Instant;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const TASK_LOG: &str = "task.log";

fn now_clock() -> String {
    let dur = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap();
    let secs = dur.as_secs();
    let h = (secs % 86400) / 3600;
    let m = (secs % 3600) / 60;
    let s = secs % 60;
    format!("{:02}:{:02}:{:02} UTC", h, m, s)
}

fn log(msg: &str) {
    let line = format!("[{}] {}", now_clock(), msg);
    println!("{}", line);
    let mut f = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(TASK_LOG)
        .unwrap();
    writeln!(f, "{}", line).unwrap();
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

fn column_exists(conn: &Connection, table: &str, column: &str) -> Result<bool> {
    let mut s = conn.prepare(&format!("PRAGMA table_info({})", table))?;
    let names: Vec<String> = s
        .query_map([], |r| r.get::<_, String>(1))?
        .filter_map(|r| r.ok())
        .collect();
    Ok(names.iter().any(|n| n == column))
}

fn main() -> Result<()> {
    let total_start = Instant::now();
    log("=== Step 63: Add number_of_works to individuals ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    if column_exists(&conn, "individuals", "number_of_works")? {
        log("[63] Column already exists — will overwrite values");
    } else {
        conn.execute_batch(
            "ALTER TABLE individuals ADD COLUMN number_of_works INTEGER NOT NULL DEFAULT 0;",
        )?;
        log("[63] Column number_of_works added (default 0)");
    }

    // Reset to 0 first so individuals with no works keep 0
    let reset = Instant::now();
    let n_reset = conn.execute("UPDATE individuals SET number_of_works = 0", [])?;
    log(&format!(
        "[63] Reset {} rows to 0 ({})",
        n_reset,
        elapsed(reset)
    ));

    // Build counts in a single UPDATE...FROM (SQLite >= 3.33)
    let upd = Instant::now();
    let n_updated = conn.execute(
        "UPDATE individuals
         SET number_of_works = c.n
         FROM (
            SELECT individual_id, COUNT(DISTINCT work_id) AS n
            FROM works
            GROUP BY individual_id
         ) AS c
         WHERE individuals.wikidata_id = c.individual_id",
        [],
    )?;
    log(&format!(
        "[63] Populated {} rows from works ({})",
        n_updated,
        elapsed(upd)
    ));

    let idx = Instant::now();
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_individuals_number_of_works
         ON individuals(number_of_works);",
    )?;
    log(&format!("[63] Index created ({})", elapsed(idx)));

    // Stats
    let total_indiv: i64 =
        conn.query_row("SELECT COUNT(*) FROM individuals", [], |r| r.get(0))?;
    let with_works: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals WHERE number_of_works > 0",
        [],
        |r| r.get(0),
    )?;
    let max_works: i64 = conn
        .query_row("SELECT MAX(number_of_works) FROM individuals", [], |r| {
            r.get(0)
        })
        .unwrap_or(0);
    let sum_works: i64 = conn.query_row(
        "SELECT COALESCE(SUM(number_of_works), 0) FROM individuals",
        [],
        |r| r.get(0),
    )?;

    log("[63] === Summary ===");
    log(&format!("[63]   Individuals total:       {}", total_indiv));
    log(&format!("[63]   With number_of_works>0:  {}", with_works));
    log(&format!("[63]   Max:                     {}", max_works));
    log(&format!("[63]   Sum (distinct work-ids): {}", sum_works));

    log("[63] Top 10 individuals by number_of_works:");
    let mut s = conn.prepare(
        "SELECT wikidata_id, name_en, number_of_works
         FROM individuals
         ORDER BY number_of_works DESC
         LIMIT 10",
    )?;
    let rows: Vec<(String, Option<String>, i64)> = s
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?
        .filter_map(|r| r.ok())
        .collect();
    for (qid, name, n) in rows {
        log(&format!("[63]   {} | {:>6} | {:?}", qid, n, name));
    }

    log(&format!(
        "=== Step 63 complete (total: {}) ===",
        elapsed(total_start)
    ));
    Ok(())
}
