/// Step 60: Create individuals_floruit_period table.
///
/// Joins biographical data from `individuals` with `individuals_floruit` (P1317),
/// then derives a `floruit_period` text range using the rules described
/// in the paper. Each row is tagged with a `method` indicating which signal
/// drove the floruit (one of: 'floruit', 'birth', 'death', 'birth_century',
/// 'death_century').
///
/// Schema:
///   wikidata_id          TEXT PRIMARY KEY
///   name_en              TEXT
///   birthdate            TEXT
///   birthdate_precision  INTEGER
///   birth_year           INTEGER     -- parsed signed year (NULL if unparseable)
///   deathdate            TEXT
///   deathdate_precision  INTEGER
///   death_year           INTEGER
///   floruit_date         TEXT
///   floruit_precision    INTEGER
///   floruit_year         INTEGER
///   floruit_period       TEXT        -- "1880-1905" or "12th c. AD"
///   method               TEXT        -- one of: 'birth', 'floruit', 'death',
///                                       'birth_century', 'death_century'
///
/// Rules (paper):
///   default span = ages 30..=55 (i.e. 25 years).
///   The end of the period is capped at CURRENT_YEAR (no future-dated floruits)
///   for year/decade-precise rules.
///   If a person hasn't reached age 30 by CURRENT_YEAR (birth_year + 30 >
///   CURRENT_YEAR), they receive no floruit.
///
///   Priority order (first applicable wins):
///   1. floruit (year/decade)  - P1317 at year/decade precision:
///      [floruit_year, floruit_year + 25], capped by death_year.
///   2. birth (with death)     - both birth and death at year/decade precision:
///      [birth+30, min(birth+55, death)].
///   3. birth (no usable death)- year/decade birth only: [birth+30, birth+55].
///   4. death                  - year/decade death only: [death-25, death].
///   5. floruit (century)      - P1317 only at century precision and no usable
///      year/decade birth or death: rounded to the nearest century, point
///      estimate.
///   6. birth_century          - century-precise birth: rounded century, point.
///   7. death_century          - century-precise death only: rounded century.
///
/// Precision codes: 11=day, 10=month, 9=year, 8=decade, 7=century, 6=millennium.
/// Year-precise = precision >= 9; decade = 8; century-or-coarser = <= 7.
///
/// If birthdate granularity differs from deathdate, we use the more precise of the two.
/// If parsed birth_year > death_year, we discard the death date.
use anyhow::{Context, Result};
use rusqlite::{params, Connection};
use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::time::Instant;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const TASK_LOG: &str = "task.log";

const FLORUIT_LO_OFFSET: i64 = 30;
const FLORUIT_HI_OFFSET: i64 = 55;
const FLORUIT_SPAN: i64 = FLORUIT_HI_OFFSET - FLORUIT_LO_OFFSET; // 25
const DEATH_ONLY_LOOKBACK: i64 = 25;
const CURRENT_YEAR: i64 = 2026;

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

/// "1st", "2nd", "3rd", "4th", ... — handles teens (11th, 12th, 13th).
fn ordinal(n: u64) -> String {
    let suffix = match n % 100 {
        11 | 12 | 13 => "th",
        _ => match n % 10 {
            1 => "st",
            2 => "nd",
            3 => "rd",
            _ => "th",
        },
    };
    format!("{}{}", n, suffix)
}

/// Convert a year (signed; negative = BC) to a century label like
/// "8th c. AD" or "2nd c. BC".
///
/// Formal convention: the n-th century AD covers years (n-1)*100+1 .. n*100,
/// so 700 -> 7th c. AD, 701 -> 8th c. AD, 1900 -> 19th c. AD, 1901 -> 20th c.
/// Wikidata sometimes stores a century at the round year (e.g. 700 to mean
/// "8th c."); per the user's note this off-by-one is a Wikidata quirk and we
/// follow the formal convention here.
/// Format a century-level period spanning two years.
/// - same century -> "12th c. AD"
/// - same era      -> "14th-15th c. AD" or "3rd-2nd c. BC"
/// - mixed era     -> "1st c. BC - 1st c. AD"
fn century_period_label(start: i64, end: i64) -> String {
    let cs = century_label(start);
    let ce = century_label(end);
    if cs == ce {
        return cs;
    }
    if let (Some(cs_n), Some(ce_n)) = (cs.strip_suffix(" c. AD"), ce.strip_suffix(" c. AD")) {
        return format!("{}-{} c. AD", cs_n, ce_n);
    }
    if let (Some(cs_n), Some(ce_n)) = (cs.strip_suffix(" c. BC"), ce.strip_suffix(" c. BC")) {
        return format!("{}-{} c. BC", cs_n, ce_n);
    }
    format!("{} - {}", cs, ce)
}

fn century_label(year: i64) -> String {
    if year > 0 {
        let n = (year + 99) / 100; // ceil(year / 100)
        format!("{} c. AD", ordinal(n as u64))
    } else if year < 0 {
        let n = (-year + 99) / 100; // ceil(|year| / 100)
        format!("{} c. BC", ordinal(n as u64))
    } else {
        // year 0: ambiguous; use 1st c. AD (Wikidata stores 0 for "1st c. AD").
        "1st c. AD".to_string()
    }
}

fn parse_year(date: &str) -> Option<i64> {
    let s = date.trim();
    if s.is_empty() || s.starts_with("_:") {
        return None;
    }
    let (negative, rest) = if let Some(r) = s.strip_prefix('-') {
        (true, r)
    } else if let Some(r) = s.strip_prefix('+') {
        (false, r)
    } else {
        (false, s)
    };
    let year_str = rest.split('-').next()?;
    let y: i64 = year_str.parse().ok()?;
    Some(if negative { -y } else { y })
}

#[derive(Default, Debug)]
struct Stats {
    total: i64,
    floruit: i64,
    birth: i64,
    death: i64,
    birth_century: i64,
    death_century: i64,
    no_period: i64,
    contradicted: i64,
}

fn main() -> Result<()> {
    let total_start = Instant::now();
    log("=== Step 60: Build individuals_floruit_period ===");

    let conn = Connection::open(DB_PATH).context("opening database")?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // Preload floruit data into a HashMap (small table, 69k rows).
    log("[60] Loading individuals_floruit into memory...");
    let mut floruit_map: HashMap<String, (Option<String>, Option<i64>, Option<i64>)> =
        HashMap::new();
    {
        let mut s = conn.prepare(
            "SELECT wikidata_id, floruit_date, floruit_precision, floruit_year
             FROM individuals_floruit",
        )?;
        let rows = s.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, Option<String>>(1)?,
                r.get::<_, Option<i64>>(2)?,
                r.get::<_, Option<i64>>(3)?,
            ))
        })?;
        for row in rows {
            let (qid, fd, fp, fy) = row?;
            floruit_map.insert(qid, (fd, fp, fy));
        }
    }
    log(&format!("[60] Loaded {} floruit entries", floruit_map.len()));

    // Recreate destination table.
    conn.execute_batch("DROP TABLE IF EXISTS individuals_floruit_period;")?;
    conn.execute_batch(
        "CREATE TABLE individuals_floruit_period (
            wikidata_id          TEXT PRIMARY KEY,
            name_en              TEXT,
            birthdate            TEXT,
            birthdate_precision  INTEGER,
            birth_year           INTEGER,
            deathdate            TEXT,
            deathdate_precision  INTEGER,
            death_year           INTEGER,
            floruit_date         TEXT,
            floruit_precision    INTEGER,
            floruit_year         INTEGER,
            floruit_period       TEXT,
            method               TEXT
        );",
    )?;
    log("[60] Created table individuals_floruit_period");

    let total_rows: i64 =
        conn.query_row("SELECT COUNT(*) FROM individuals", [], |r| r.get(0))?;
    log(&format!("[60] Will process {} individuals", total_rows));

    let step = Instant::now();
    let tx = conn.unchecked_transaction()?;

    let mut stats = Stats::default();

    {
        let mut sel = tx.prepare(
            "SELECT wikidata_id, name_en, birthdate, birthdate_precision,
                    deathdate, deathdate_precision
             FROM individuals",
        )?;
        let mut ins = tx.prepare(
            "INSERT INTO individuals_floruit_period (
                wikidata_id, name_en,
                birthdate, birthdate_precision, birth_year,
                deathdate, deathdate_precision, death_year,
                floruit_date, floruit_precision, floruit_year,
                floruit_period, method
            ) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13)",
        )?;

        let mut rows = sel.query([])?;
        while let Some(row) = rows.next()? {
            stats.total += 1;

            let qid: String = row.get(0)?;
            let name: Option<String> = row.get(1)?;
            let birthdate: Option<String> = row.get(2)?;
            let bprec: Option<i64> = row.get(3)?;
            let deathdate: Option<String> = row.get(4)?;
            let dprec: Option<i64> = row.get(5)?;

            let mut birth_year = birthdate.as_deref().and_then(parse_year);
            let mut death_year = deathdate.as_deref().and_then(parse_year);

            // Rule: if birth > death, drop death (contradicted dates).
            if let (Some(b), Some(d)) = (birth_year, death_year) {
                if b > d {
                    stats.contradicted += 1;
                    death_year = None;
                }
            }

            // Pull P1317 floruit (if any).
            let (fdate, fprec, fyear) = floruit_map
                .get(&qid)
                .cloned()
                .unwrap_or((None, None, None));

            // Decide effective precision: more precise of the two birth/death.
            // We treat None precision as "unknown" -> very coarse.
            let eff_prec = match (bprec, dprec) {
                (Some(a), Some(b)) => Some(a.max(b)),
                (Some(a), None) => Some(a),
                (None, Some(b)) => Some(b),
                _ => None,
            };

            // Derive floruit_start / floruit_end / method.
            let (start, end, method) = compute_floruit(
                birth_year,
                bprec,
                death_year,
                dprec,
                eff_prec,
                fyear,
                fprec,
            );

            match method {
                "floruit" => stats.floruit += 1,
                "birth" => stats.birth += 1,
                "death" => stats.death += 1,
                "birth_century" => stats.birth_century += 1,
                "death_century" => stats.death_century += 1,
                _ => stats.no_period += 1,
            }

            // Decide whether to display this row at century granularity.
            let century_display = matches!(method, "birth_century" | "death_century")
                || (method == "floruit" && matches!(fprec, Some(p) if (5..=7).contains(&p)));

            let period = match (start, end) {
                (Some(s), Some(e)) => {
                    if century_display {
                        Some(century_period_label(s, e))
                    } else {
                        Some(format!("{}-{}", s, e))
                    }
                }
                _ => None,
            };

            ins.execute(params![
                qid,
                name,
                birthdate,
                bprec,
                birth_year,
                deathdate,
                dprec,
                death_year,
                fdate,
                fprec,
                fyear,
                period,
                if method.is_empty() { None } else { Some(method) },
            ])?;

            if stats.total % 250_000 == 0 {
                log(&format!(
                    "[60]   processed {}/{} ({})",
                    stats.total,
                    total_rows,
                    elapsed(step)
                ));
            }
        }
    }

    tx.commit()?;
    log(&format!(
        "[60] Insert complete: {} rows in {}",
        stats.total,
        elapsed(step)
    ));

    let idx = Instant::now();
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_fp_method        ON individuals_floruit_period(method);
         CREATE INDEX IF NOT EXISTS idx_fp_birth_year    ON individuals_floruit_period(birth_year);
         CREATE INDEX IF NOT EXISTS idx_fp_death_year    ON individuals_floruit_period(death_year);",
    )?;
    log(&format!("[60] Indexes created ({})", elapsed(idx)));

    log("[60] === Summary ===");
    log(&format!("[60]   total rows:       {}", stats.total));
    log(&format!("[60]   floruit:          {}", stats.floruit));
    log(&format!("[60]   birth:            {}", stats.birth));
    log(&format!("[60]   death:            {}", stats.death));
    log(&format!("[60]   birth_century:    {}", stats.birth_century));
    log(&format!("[60]   death_century:    {}", stats.death_century));
    log(&format!("[60]   no_period:        {}", stats.no_period));
    log(&format!("[60]   contradicted dates dropped: {}", stats.contradicted));

    log("[60] Sample rows:");
    let mut s = conn.prepare(
        "SELECT wikidata_id, name_en, birth_year, death_year, floruit_year,
                floruit_period, method
         FROM individuals_floruit_period
         WHERE floruit_period IS NOT NULL
         ORDER BY RANDOM() LIMIT 10",
    )?;
    let rows: Vec<(
        String,
        Option<String>,
        Option<i64>,
        Option<i64>,
        Option<i64>,
        Option<String>,
        Option<String>,
    )> = s
        .query_map([], |r| {
            Ok((
                r.get(0)?,
                r.get(1)?,
                r.get(2)?,
                r.get(3)?,
                r.get(4)?,
                r.get(5)?,
                r.get(6)?,
            ))
        })?
        .filter_map(|r| r.ok())
        .collect();
    for (q, n, by, dy, fy, p, m) in rows {
        log(&format!(
            "[60]   {} | {:?} | b={:?} d={:?} f={:?} -> {:?} ({:?})",
            q, n, by, dy, fy, p, m
        ));
    }

    log(&format!(
        "=== Step 60 complete (total: {}) ===",
        elapsed(total_start)
    ));
    Ok(())
}

/// Compute floruit_start, floruit_end, and the method used.
/// Returns (None, None, "") when the data is too sparse for any rule.
fn compute_floruit(
    birth_year: Option<i64>,
    birth_prec: Option<i64>,
    death_year: Option<i64>,
    death_prec: Option<i64>,
    _eff_prec: Option<i64>,
    floruit_year: Option<i64>,
    floruit_prec: Option<i64>,
) -> (Option<i64>, Option<i64>, &'static str) {
    let decade_precise = |p: Option<i64>| matches!(p, Some(x) if x >= 8);
    let century_precise = |p: Option<i64>| matches!(p, Some(x) if (5..=7).contains(&x));

    let birth_usable = birth_year.is_some() && decade_precise(birth_prec);
    let death_usable = death_year.is_some() && decade_precise(death_prec);
    let floruit_year_usable = floruit_year.is_some() && decade_precise(floruit_prec);

    // Rule 1: P1317 at year/decade precision wins.
    if floruit_year_usable {
        let fy = floruit_year.unwrap();
        let start = fy;
        let mut end = fy + FLORUIT_SPAN;
        if death_usable {
            let d = death_year.unwrap();
            if d < end {
                end = d;
            }
        }
        let end = end.min(CURRENT_YEAR);
        let start = start.min(end);
        return (Some(start), Some(end), "floruit");
    }

    // Rule 2: birth + death both at year/decade precision.
    if birth_usable && death_usable {
        let b = birth_year.unwrap();
        let d = death_year.unwrap();
        // Person not yet 30 by the current year -> no floruit yet.
        if b + FLORUIT_LO_OFFSET > CURRENT_YEAR {
            return (None, None, "");
        }
        let start = b + FLORUIT_LO_OFFSET;
        let end = (b + FLORUIT_HI_OFFSET).min(d).min(CURRENT_YEAR);
        if start <= end {
            return (Some(start), Some(end), "birth");
        }
        // Person died before age 30 -> floruit is just up to death.
        let end = d.min(CURRENT_YEAR);
        return (Some(end.min(start)), Some(end), "birth");
    }

    // Rule 3: only birth usable.
    if birth_usable && !death_usable {
        let b = birth_year.unwrap();
        // Person not yet 30 by the current year -> no floruit yet.
        if b + FLORUIT_LO_OFFSET > CURRENT_YEAR {
            return (None, None, "");
        }
        let start = b + FLORUIT_LO_OFFSET;
        let end = (b + FLORUIT_HI_OFFSET).min(CURRENT_YEAR);
        return (Some(start.min(end)), Some(end), "birth");
    }

    // Rule 4: only death usable.
    if death_usable && !birth_usable {
        let d = death_year.unwrap();
        let end = d.min(CURRENT_YEAR);
        let start = end - DEATH_ONLY_LOOKBACK;
        return (Some(start), Some(end), "death");
    }

    // Rule 5: P1317 at century precision (only when no usable year/decade birth/death).
    // The raw year is kept as a point estimate; century_label later turns it into
    // a formal-century string ("8th c. AD" etc.).
    if let Some(fy) = floruit_year {
        if century_precise(floruit_prec) {
            return (Some(fy), Some(fy), "floruit");
        }
    }

    // Rule 6: century-precise birth. If death is also century-precise we
    // extend the period to include the death century (e.g. birth 15th c.,
    // death 16th c. -> "15th-16th c. AD"). Otherwise it's a point estimate.
    if let Some(by) = birth_year {
        if century_precise(birth_prec) {
            let end = match (death_year, death_prec) {
                (Some(dy), dp) if century_precise(dp) && dy >= by => dy,
                _ => by,
            };
            return (Some(by), Some(end), "birth_century");
        }
    }

    // Rule 7: century-precise death (point estimate).
    if let Some(dy) = death_year {
        if century_precise(death_prec) {
            return (Some(dy), Some(dy), "death_century");
        }
    }

    (None, None, "")
}

