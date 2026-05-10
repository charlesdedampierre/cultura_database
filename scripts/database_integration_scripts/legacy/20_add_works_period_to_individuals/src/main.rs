// Add `works_period` to the `individuals` table.
//
// Per individual, look at every row in `works` and compute the work's
// effective year as:
//   - inception_date year, if present (preferred — the year the author
//     actually created the work)
//   - else publication_date year (later editions / re-publications)
//   - else NULL (skip that work)
//
// Then aggregate per individual to (min_year, max_year), and cap max_year
// at the author's death year so posthumous re-publications never push the
// activity period beyond the lifetime. The death-year cap uses the first
// non-null value of:
//   1. deathdate                       (Wikidata P570)
//   2. deathdate_in_description        (parsed from description string)
//   3. deathdate_from_CV               (Cross-Verified DB)
//   4. deathdate_from_life_expectancy  (birth + life-expectancy estimate)
// If every dated work is post-mortem (min_year > death_year), the
// individual gets no works_period (treated as no usable signal).
//
// Final value:
//   - if all years equal: "1873"
//   - else:               "1851-1894"
//   - if no dated work or all post-mortem: NULL
//
// ISO timestamps stored in works are like "1873-09-04T00:00:00Z" or
// "-0500-01-01T00:00:00Z" for BCE. The leading optional minus sign is
// preserved.
//
// Strategy: one SQL pass over works (grouped by individual_id) into temp.iy,
// one pass over individuals to build temp.idy with the capped death year,
// clip iy by idy, then one UPDATE join into individuals.

use anyhow::{Context, Result};
use chrono::Local;
use rusqlite::{Connection, OpenFlags};
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::time::Instant;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const LOG_PATH: &str = "logs/20_add_works_period_to_individuals.log";

fn log_line(log: &mut std::fs::File, msg: &str) {
    let stamped = format!("[{}] {}", Local::now().format("%Y-%m-%d %H:%M:%S"), msg);
    println!("{stamped}");
    let _ = writeln!(log, "{stamped}");
    let _ = log.flush();
}

fn add_column_if_missing(conn: &Connection, col: &str, ty: &str) -> Result<()> {
    let exists: bool = conn
        .prepare("SELECT 1 FROM pragma_table_info('individuals') WHERE name = ?1")?
        .query_map([col], |_| Ok(()))?
        .next()
        .is_some();
    if !exists {
        conn.execute_batch(&format!("ALTER TABLE individuals ADD COLUMN {col} {ty};"))?;
    }
    Ok(())
}

fn main() -> Result<()> {
    if !Path::new(DB_PATH).exists() {
        anyhow::bail!("DB not found at {DB_PATH}. Run from project root.");
    }
    std::fs::create_dir_all("logs").ok();
    let mut log = OpenOptions::new()
        .create(true)
        .append(true)
        .open(LOG_PATH)?;

    log_line(&mut log, "=== 20_add_works_period_to_individuals START ===");
    let started = Instant::now();

    let conn = Connection::open_with_flags(
        DB_PATH,
        OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .with_context(|| format!("opening {DB_PATH}"))?;

    conn.pragma_update(None, "journal_mode", "WAL")?;
    conn.pragma_update(None, "synchronous", "NORMAL")?;
    conn.pragma_update(None, "temp_store", "MEMORY")?;
    conn.pragma_update(None, "cache_size", -1_000_000)?;

    log_line(&mut log, "ALTER TABLE individuals ADD COLUMN works_period TEXT (if missing)");
    add_column_if_missing(&conn, "works_period", "TEXT")?;

    // --- Build temp table of (individual_id, min_year, max_year) ---------
    //
    // Effective year per work row = year(inception_date) ?? year(publication_date)
    // (inception is the year the *author* actually created the work; publication
    //  may be a later edition by editors, even centuries posthumous.)
    //
    // Year extraction handles BCE: ISO strings either start with '-' (then
    // the year part is everything up to the next '-' starting at index 1
    // — taken as a negative integer) or with a digit (year is the first
    // 4 chars). We use SQLite's substr/CAST: a leading '-' turns CAST into
    // a negative int automatically, so substr(date,1,5) for BCE and
    // substr(date,1,4) for CE both produce the right integer.
    log_line(&mut log, "build temp.iy with min/max effective year per individual");
    conn.execute_batch(
        "DROP TABLE IF EXISTS temp.iy;
         CREATE TEMP TABLE iy (
             individual_id TEXT PRIMARY KEY,
             min_year INTEGER NOT NULL,
             max_year INTEGER NOT NULL
         );",
    )?;

    let build_started = Instant::now();
    let inserted = conn.execute(
        "INSERT INTO temp.iy (individual_id, min_year, max_year)
         SELECT individual_id, MIN(eff_year), MAX(eff_year)
         FROM (
           SELECT individual_id,
                  CAST(
                    CASE
                      WHEN inception_date IS NOT NULL THEN
                        CASE WHEN substr(inception_date,1,1)='-'
                             THEN substr(inception_date,1,5)
                             ELSE substr(inception_date,1,4) END
                      WHEN publication_date IS NOT NULL THEN
                        CASE WHEN substr(publication_date,1,1)='-'
                             THEN substr(publication_date,1,5)
                             ELSE substr(publication_date,1,4) END
                      ELSE NULL
                    END
                  AS INTEGER) AS eff_year
           FROM works
           WHERE publication_date IS NOT NULL OR inception_date IS NOT NULL
         )
         WHERE eff_year IS NOT NULL
         GROUP BY individual_id;",
        [],
    )?;
    log_line(
        &mut log,
        &format!("temp.iy populated: {inserted} individuals in {:.1}s",
                 build_started.elapsed().as_secs_f64()),
    );

    // --- Build temp.idy: best-available death year per individual ---------
    //
    // Priority: deathdate (Wikidata P570) > deathdate_in_description
    //         > deathdate_from_CV       > deathdate_from_life_expectancy.
    // Same BCE-safe substr trick as above. deathdate_in_description is
    // already INTEGER so it's used directly.
    log_line(&mut log, "build temp.idy with capped death year per individual");
    conn.execute_batch(
        "DROP TABLE IF EXISTS temp.idy;
         CREATE TEMP TABLE idy (
             wikidata_id TEXT PRIMARY KEY,
             death_year INTEGER NOT NULL
         );",
    )?;
    let idy_started = Instant::now();
    let idy_inserted = conn.execute(
        "INSERT INTO temp.idy (wikidata_id, death_year)
         SELECT wikidata_id,
                COALESCE(
                  CASE WHEN deathdate IS NOT NULL THEN
                    CAST(CASE WHEN substr(deathdate,1,1)='-'
                              THEN substr(deathdate,1,5)
                              ELSE substr(deathdate,1,4) END AS INTEGER)
                  END,
                  deathdate_in_description,
                  CASE WHEN deathdate_from_CV IS NOT NULL THEN
                    CAST(CASE WHEN substr(deathdate_from_CV,1,1)='-'
                              THEN substr(deathdate_from_CV,1,5)
                              ELSE substr(deathdate_from_CV,1,4) END AS INTEGER)
                  END,
                  CASE WHEN deathdate_from_life_expectancy IS NOT NULL THEN
                    CAST(CASE WHEN substr(deathdate_from_life_expectancy,1,1)='-'
                              THEN substr(deathdate_from_life_expectancy,1,5)
                              ELSE substr(deathdate_from_life_expectancy,1,4) END AS INTEGER)
                  END
                ) AS death_year
         FROM individuals
         WHERE deathdate IS NOT NULL
            OR deathdate_in_description IS NOT NULL
            OR deathdate_from_CV IS NOT NULL
            OR deathdate_from_life_expectancy IS NOT NULL;",
        [],
    )?;
    // Defensive: drop rows whose COALESCE somehow yielded NULL (shouldn't happen,
    // but the table is declared NOT NULL).
    log_line(
        &mut log,
        &format!("temp.idy populated: {idy_inserted} individuals in {:.1}s",
                 idy_started.elapsed().as_secs_f64()),
    );

    // --- Apply death-year cap to temp.iy ---------------------------------
    let cap_started = Instant::now();
    let dropped = conn.execute(
        "DELETE FROM iy
         WHERE EXISTS (
           SELECT 1 FROM idy d
           WHERE d.wikidata_id = iy.individual_id
             AND d.death_year < iy.min_year
         );",
        [],
    )?;
    let capped = conn.execute(
        "UPDATE iy
         SET max_year = (SELECT d.death_year FROM idy d
                         WHERE d.wikidata_id = iy.individual_id)
         WHERE EXISTS (
           SELECT 1 FROM idy d
           WHERE d.wikidata_id = iy.individual_id
             AND d.death_year < iy.max_year
         );",
        [],
    )?;
    log_line(
        &mut log,
        &format!("death cap: dropped {dropped} all-post-mortem rows, capped {capped} max_year values in {:.1}s",
                 cap_started.elapsed().as_secs_f64()),
    );

    // --- UPDATE individuals.works_period ------------------------------
    log_line(&mut log, "clear stale works_period, then UPDATE FROM temp.iy");
    let upd_started = Instant::now();
    // Clear first so individuals dropped from iy on re-runs don't keep stale values.
    conn.execute("UPDATE individuals SET works_period = NULL WHERE works_period IS NOT NULL", [])?;
    let touched = conn.execute(
        "UPDATE individuals
         SET works_period = (
            SELECT CASE
                     WHEN iy.min_year = iy.max_year THEN CAST(iy.min_year AS TEXT)
                     ELSE CAST(iy.min_year AS TEXT) || '-' || CAST(iy.max_year AS TEXT)
                   END
            FROM temp.iy iy
            WHERE iy.individual_id = individuals.wikidata_id
         )
         WHERE individuals.wikidata_id IN (SELECT individual_id FROM temp.iy);",
        [],
    )?;
    log_line(
        &mut log,
        &format!("UPDATE touched {touched} rows in {:.1}s",
                 upd_started.elapsed().as_secs_f64()),
    );

    // --- Summary ------------------------------------------------------
    let total: i64 = conn.query_row("SELECT COUNT(*) FROM individuals", [], |r| r.get(0))?;
    let with_period: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals WHERE works_period IS NOT NULL",
        [], |r| r.get(0),
    )?;
    let single_year: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals WHERE works_period IS NOT NULL AND instr(substr(works_period,2),'-')=0",
        [], |r| r.get(0),
    )?;
    let span: i64 = with_period - single_year;

    log_line(
        &mut log,
        &format!("DONE individuals_total={total} with_works_period={with_period} \
                  single_year={single_year} span_min_max={span} total_elapsed={:.1}s",
                 started.elapsed().as_secs_f64()),
    );
    log_line(&mut log, "=== 20_add_works_period_to_individuals END ===");
    Ok(())
}
