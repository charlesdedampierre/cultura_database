// Add estimated_birthdate_from_life_expectancy and
// estimated_deathdate_from_life_expectancy to the `individuals` table.
//
// For every individual missing exactly one of (birthdate, deathdate) but
// having a year-precision (>= 9) anchor on the other side, we estimate
// the missing date using a cascading lookup of median life expectancy
// (= deathdate - birthdate) computed from the ~3.1M individuals that
// already have both dates at year-or-finer precision:
//
//   1. (CV occupational category, 20-year period bin)  -- both available
//   2. CV occupational category overall                -- if period sparse
//   3. 20-year period overall                          -- no CV category
//   4. global median                                   -- last resort
//
// Period bin is keyed on whichever date the target has — birth-anchored
// for "missing only deathdate", death-anchored for "missing only
// birthdate". We therefore build two parallel cascades.
//
// Output: ISO 'YYYY-01-01' (or '-YYYY-01-01' for BCE), matching how
// existing `birthdate` / `deathdate` columns store year-precision values.
//
// Strategy: build estimates in memory, write into a temp table keyed by
// wikidata_id, then a single UPDATE … FROM temp.est rather than millions
// of per-row UPDATEs.

use anyhow::{Context, Result};
use chrono::Local;
use csv::ReaderBuilder;
use flate2::read::GzDecoder;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{Connection, OpenFlags};
use std::collections::HashMap;
use std::fs::{File, OpenOptions};
use std::io::{BufReader, Write};
use std::path::Path;
use std::time::Instant;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const CV_PATH: &str =
    "data/similar_databases/cross-verified-database/cross-verified-database.utf8.csv.gz";
const LOG_PATH: &str = "logs/21_estimate_dates_from_life_expectancy.log";

const BIN_WIDTH: i32 = 20;
const MIN_PRECISION: i64 = 9; // year-level
const MIN_BIN_SAMPLES: usize = 5; // training bins must have >=5 to be used directly

fn log_line(log: &mut File, msg: &str) {
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
        conn.execute_batch(&format!(
            "ALTER TABLE individuals ADD COLUMN {col} {ty};"
        ))?;
    }
    Ok(())
}

/// Parse a Wikidata ISO date into a fractional year.
/// Returns None for blank-nodes ('_:bn...'), empty strings, or unparsable input.
/// Handles BC dates of the form '-YYYY-MM-DD' (sign on year). Missing
/// month/day default to 1.
fn parse_year_frac(s: &str) -> Option<f64> {
    if s.is_empty() || s.starts_with("_:") {
        return None;
    }
    let bytes = s.as_bytes();
    let (sign, rest) = if bytes[0] == b'-' {
        (-1.0_f64, &s[1..])
    } else {
        (1.0_f64, s)
    };
    // year part: digits up to first '-'
    let mut parts = rest.splitn(3, '-');
    let y_str = parts.next()?;
    let y: i64 = y_str.parse().ok()?;
    let m: u32 = parts
        .next()
        .and_then(|t| t.parse().ok())
        .unwrap_or(1);
    let d: u32 = parts
        .next()
        .and_then(|t| t.parse().ok())
        .unwrap_or(1);
    let m = m.clamp(1, 12);
    let d = d.clamp(1, 31);
    let frac = (30.0 * (m as f64 - 1.0) + (d as f64 - 1.0)) / 365.0;
    Some(sign * (y as f64 + frac))
}

/// Format an integer year as ISO 'YYYY-01-01' (negative => BC).
fn fmt_iso_year(year: i32) -> String {
    if year < 0 {
        format!("-{:04}-01-01", -year)
    } else {
        format!("{:04}-01-01", year)
    }
}

/// Floor to the nearest BIN_WIDTH (handles negative years correctly).
fn period_bin(year_frac: f64) -> i32 {
    let y = year_frac.floor() as i32;
    // Rust's % can produce negatives; emulate Python's `//` floor-div by BIN_WIDTH
    let rem = ((y % BIN_WIDTH) + BIN_WIDTH) % BIN_WIDTH;
    y - rem
}

fn median_in_place(v: &mut [f64]) -> f64 {
    debug_assert!(!v.is_empty());
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let n = v.len();
    if n % 2 == 1 {
        v[n / 2]
    } else {
        0.5 * (v[n / 2 - 1] + v[n / 2])
    }
}

fn group_median_with_count<K: std::hash::Hash + Eq + Clone>(
    groups: &mut HashMap<K, Vec<f64>>,
) -> HashMap<K, (f64, usize)> {
    let mut out = HashMap::with_capacity(groups.len());
    for (k, v) in groups.iter_mut() {
        let n = v.len();
        if n == 0 {
            continue;
        }
        let m = median_in_place(v);
        out.insert(k.clone(), (m, n));
    }
    out
}

/// Cascade lookup tables anchored on either birth or death period.
struct Cascade {
    cat_period: HashMap<(String, i32), (f64, usize)>,
    cat_only: HashMap<String, (f64, usize)>,
    period_only: HashMap<i32, (f64, usize)>,
    global_med: f64,
}

#[derive(Clone, Copy, Debug)]
enum Source {
    CategoryAndPeriod,
    Category,
    Period,
    Global,
}

impl Source {
    fn label(&self) -> &'static str {
        match self {
            Source::CategoryAndPeriod => "category+period",
            Source::Category => "category",
            Source::Period => "period",
            Source::Global => "global",
        }
    }
}

fn cascade_lookup(
    cat: Option<&str>,
    period: i32,
    casc: &Cascade,
) -> (f64, Source) {
    if let Some(c) = cat {
        if let Some((m, n)) = casc.cat_period.get(&(c.to_string(), period)) {
            if *n >= MIN_BIN_SAMPLES {
                return (*m, Source::CategoryAndPeriod);
            }
        }
        if let Some((m, _)) = casc.cat_only.get(c) {
            return (*m, Source::Category);
        }
    }
    if let Some((m, n)) = casc.period_only.get(&period) {
        if *n >= MIN_BIN_SAMPLES {
            return (*m, Source::Period);
        }
    }
    (casc.global_med, Source::Global)
}

fn build_cascade(
    train: &[TrainRow],
    anchor_birth: bool,
) -> Cascade {
    let mut g_cp: HashMap<(String, i32), Vec<f64>> = HashMap::new();
    let mut g_c: HashMap<String, Vec<f64>> = HashMap::new();
    let mut g_p: HashMap<i32, Vec<f64>> = HashMap::new();
    let mut g_all: Vec<f64> = Vec::with_capacity(train.len());

    for r in train {
        let bin = if anchor_birth { r.bin_birth } else { r.bin_death };
        g_p.entry(bin).or_default().push(r.longevity);
        g_all.push(r.longevity);
        if let Some(c) = &r.cat {
            g_cp.entry((c.clone(), bin)).or_default().push(r.longevity);
            g_c.entry(c.clone()).or_default().push(r.longevity);
        }
    }
    let cat_period = group_median_with_count(&mut g_cp);
    let cat_only = group_median_with_count(&mut g_c);
    let period_only = group_median_with_count(&mut g_p);
    let global_med = median_in_place(&mut g_all);
    Cascade {
        cat_period,
        cat_only,
        period_only,
        global_med,
    }
}

#[derive(Clone)]
struct TrainRow {
    longevity: f64,
    bin_birth: i32,
    bin_death: i32,
    cat: Option<String>,
}

/// Read CV CSV.gz and return a (wikidata_id -> level1_main_occ) map.
/// "Missing" categories are dropped.
fn load_cv_categories(path: &str) -> Result<HashMap<String, String>> {
    let f = File::open(path).with_context(|| format!("opening {path}"))?;
    let gz = GzDecoder::new(BufReader::new(f));
    let mut rdr = ReaderBuilder::new()
        .has_headers(true)
        .from_reader(BufReader::new(gz));

    let headers = rdr.headers()?.clone();
    let idx_id = headers
        .iter()
        .position(|h| h == "wikidata_code")
        .context("CV: missing 'wikidata_code'")?;
    let idx_cat = headers
        .iter()
        .position(|h| h == "level1_main_occ")
        .context("CV: missing 'level1_main_occ'")?;

    let mut out: HashMap<String, String> = HashMap::with_capacity(2_300_000);
    for rec in rdr.records() {
        let rec = rec?;
        let id = rec.get(idx_id).unwrap_or("").trim();
        let cat = rec.get(idx_cat).unwrap_or("").trim();
        if id.is_empty() || cat.is_empty() || cat == "Missing" {
            continue;
        }
        out.insert(id.to_string(), cat.to_string());
    }
    Ok(out)
}

fn main() -> Result<()> {
    let started = Instant::now();
    let _ = std::fs::create_dir_all("logs");
    let mut log = OpenOptions::new()
        .create(true)
        .append(true)
        .open(LOG_PATH)
        .with_context(|| format!("opening {LOG_PATH}"))?;

    log_line(&mut log, "=== 21_estimate_dates_from_life_expectancy START ===");
    if !Path::new(DB_PATH).exists() {
        anyhow::bail!("DB not found at {DB_PATH}");
    }

    log_line(&mut log, "Loading CV level1_main_occ ...");
    let cv = load_cv_categories(CV_PATH)?;
    log_line(
        &mut log,
        &format!("  CV (id, category) entries: {}", cv.len()),
    );

    let conn = Connection::open_with_flags(DB_PATH, OpenFlags::SQLITE_OPEN_READ_WRITE)?;
    conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")?;

    let total_individuals: i64 =
        conn.query_row("SELECT COUNT(*) FROM individuals", [], |r| r.get(0))?;
    log_line(
        &mut log,
        &format!("Loading individuals from SQLite ({total_individuals} rows) ..."),
    );

    // ---- Single pass over individuals: build training set + collect targets ----
    let pb = ProgressBar::new(total_individuals as u64);
    pb.set_style(
        ProgressStyle::with_template(
            "  {bar:40} {pos}/{len} {percent}% (elapsed {elapsed_precise})",
        )?
        .progress_chars("=>-"),
    );

    let mut train: Vec<TrainRow> = Vec::with_capacity(3_200_000);
    // targets needing deathdate (have only birth)
    let mut tgt_need_death: Vec<(String, f64, Option<String>)> = Vec::with_capacity(3_000_000);
    // targets needing birthdate (have only death)
    let mut tgt_need_birth: Vec<(String, f64, Option<String>)> = Vec::with_capacity(2_000_000);

    let mut n_seen = 0u64;
    let mut n_both = 0u64;
    let mut n_only_b = 0u64;
    let mut n_only_d = 0u64;
    let mut n_neither = 0u64;

    {
    let mut stmt = conn.prepare(
        "SELECT wikidata_id, birthdate, deathdate, birthdate_precision, deathdate_precision
         FROM individuals",
    )?;
    let mut rows = stmt.query([])?;

    while let Some(r) = rows.next()? {
        n_seen += 1;
        if n_seen.is_multiple_of(200_000) {
            pb.set_position(n_seen);
        }
        let wid: String = r.get(0)?;
        let bd: Option<String> = r.get(1)?;
        let dd: Option<String> = r.get(2)?;
        let bp: Option<i64> = r.get(3)?;
        let dp: Option<i64> = r.get(4)?;

        let by = bd
            .as_deref()
            .and_then(parse_year_frac)
            .filter(|_| bp.unwrap_or(0) >= MIN_PRECISION);
        let dy = dd
            .as_deref()
            .and_then(parse_year_frac)
            .filter(|_| dp.unwrap_or(0) >= MIN_PRECISION);

        match (by, dy) {
            (Some(b), Some(d)) => {
                let lon = d - b;
                if (0.0..=130.0).contains(&lon) {
                    train.push(TrainRow {
                        longevity: lon,
                        bin_birth: period_bin(b),
                        bin_death: period_bin(d),
                        cat: cv.get(&wid).cloned(),
                    });
                }
                n_both += 1;
            }
            (Some(b), None) => {
                tgt_need_death.push((wid.clone(), b, cv.get(&wid).cloned()));
                n_only_b += 1;
            }
            (None, Some(d)) => {
                tgt_need_birth.push((wid.clone(), d, cv.get(&wid).cloned()));
                n_only_d += 1;
            }
            (None, None) => {
                n_neither += 1;
            }
        }
    }
    pb.set_position(n_seen);
    pb.finish_and_clear();
    } // drop stmt + rows so we can move conn into tx_conn later

    log_line(
        &mut log,
        &format!(
            "  individuals scanned: seen={n_seen} both={n_both} only_birth={n_only_b} only_death={n_only_d} neither={n_neither}"
        ),
    );
    log_line(
        &mut log,
        &format!("  training rows (longevity in [0,130]): {}", train.len()),
    );

    // ---- Build cascades ----
    log_line(&mut log, "Building cascade lookups (birth-anchored, death-anchored) ...");
    let casc_birth = build_cascade(&train, true);
    let casc_death = build_cascade(&train, false);
    log_line(
        &mut log,
        &format!(
            "  global median: birth-anchored={:.2}, death-anchored={:.2}",
            casc_birth.global_med, casc_death.global_med
        ),
    );

    // ---- Resolve estimates ----
    log_line(&mut log, "Resolving estimates ...");
    let mut estimates: Vec<(String, Option<String>, Option<String>, &'static str)> =
        Vec::with_capacity(tgt_need_death.len() + tgt_need_birth.len());

    let mut src_counts: HashMap<&'static str, usize> = HashMap::new();

    for (wid, by, cat) in tgt_need_death.into_iter() {
        let bin = period_bin(by);
        let (le, src) = cascade_lookup(cat.as_deref(), bin, &casc_birth);
        let est_year = (by + le).floor() as i32;
        let iso = fmt_iso_year(est_year);
        *src_counts.entry(src.label()).or_insert(0) += 1;
        estimates.push((wid, None, Some(iso), src.label()));
    }

    for (wid, dy, cat) in tgt_need_birth.into_iter() {
        let bin = period_bin(dy);
        let (le, src) = cascade_lookup(cat.as_deref(), bin, &casc_death);
        let est_year = (dy - le).floor() as i32;
        let iso = fmt_iso_year(est_year);
        *src_counts.entry(src.label()).or_insert(0) += 1;
        estimates.push((wid, Some(iso), None, src.label()));
    }

    log_line(
        &mut log,
        &format!("  total estimates produced: {}", estimates.len()),
    );
    let mut src_pairs: Vec<(&'static str, usize)> = src_counts.into_iter().collect();
    src_pairs.sort_by_key(|(_, n)| std::cmp::Reverse(*n));
    for (k, n) in src_pairs {
        log_line(&mut log, &format!("    source={k}  n={n}"));
    }

    // ---- Write back: temp table + UPDATE FROM ----
    log_line(&mut log, "Writing estimates to temp.est ...");
    add_column_if_missing(&conn, "estimated_birthdate_from_life_expectancy", "TEXT")?;
    add_column_if_missing(&conn, "estimated_deathdate_from_life_expectancy", "TEXT")?;

    conn.execute_batch(
        "ATTACH ':memory:' AS temp_db;
         CREATE TABLE temp_db.est (
            wikidata_id TEXT PRIMARY KEY,
            est_birth   TEXT,
            est_death   TEXT,
            src         TEXT
         );",
    )?;

    let mut tx_conn = conn;
    let pb = ProgressBar::new(estimates.len() as u64);
    pb.set_style(
        ProgressStyle::with_template(
            "  insert {bar:40} {pos}/{len} {percent}% (elapsed {elapsed_precise})",
        )?
        .progress_chars("=>-"),
    );

    let tx = tx_conn.transaction()?;
    {
        let mut ins = tx.prepare(
            "INSERT INTO temp_db.est (wikidata_id, est_birth, est_death, src) VALUES (?1, ?2, ?3, ?4)",
        )?;
        for (i, (wid, eb, ed, src)) in estimates.iter().enumerate() {
            ins.execute(rusqlite::params![wid, eb, ed, src])?;
            if i.is_multiple_of(50_000) {
                pb.set_position(i as u64);
            }
        }
        pb.set_position(estimates.len() as u64);
    }
    tx.commit()?;
    pb.finish_and_clear();

    log_line(&mut log, "UPDATE individuals FROM temp.est ...");
    let upd_started = Instant::now();
    let touched_b = tx_conn.execute(
        "UPDATE individuals
         SET estimated_birthdate_from_life_expectancy = (
            SELECT est_birth FROM temp_db.est WHERE temp_db.est.wikidata_id = individuals.wikidata_id
         )
         WHERE individuals.wikidata_id IN (
            SELECT wikidata_id FROM temp_db.est WHERE est_birth IS NOT NULL
         );",
        [],
    )?;
    let touched_d = tx_conn.execute(
        "UPDATE individuals
         SET estimated_deathdate_from_life_expectancy = (
            SELECT est_death FROM temp_db.est WHERE temp_db.est.wikidata_id = individuals.wikidata_id
         )
         WHERE individuals.wikidata_id IN (
            SELECT wikidata_id FROM temp_db.est WHERE est_death IS NOT NULL
         );",
        [],
    )?;
    log_line(
        &mut log,
        &format!(
            "UPDATE touched birth={touched_b} death={touched_d} in {:.1}s",
            upd_started.elapsed().as_secs_f64()
        ),
    );

    // ---- Final stats ----
    let n_b: i64 = tx_conn.query_row(
        "SELECT COUNT(*) FROM individuals WHERE estimated_birthdate_from_life_expectancy IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    let n_d: i64 = tx_conn.query_row(
        "SELECT COUNT(*) FROM individuals WHERE estimated_deathdate_from_life_expectancy IS NOT NULL",
        [],
        |r| r.get(0),
    )?;
    log_line(
        &mut log,
        &format!(
            "DONE estimated_birthdate={n_b} estimated_deathdate={n_d} total_elapsed={:.1}s",
            started.elapsed().as_secs_f64()
        ),
    );
    log_line(&mut log, "=== 21_estimate_dates_from_life_expectancy END ===");

    Ok(())
}
