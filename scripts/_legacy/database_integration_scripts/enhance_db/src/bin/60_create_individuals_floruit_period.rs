/// Step 60: Create individuals_floruit_period table.
///
/// Pulls all biographical signals from the `individuals` table directly
/// (P569 birth, P570 death, P1317 floruit, plus the description-derived
/// columns: birthdate_in_description / deathdate_in_description /
/// floruit_year_in_description / dates_in_description), and assigns each
/// individual a single, mutually-exclusive `method` describing the source
/// of the floruit period.  Individuals with no usable signal but with a
/// dated cliopatria polity get a `polity_only` residual.
///
/// Schema:
///   wikidata_id          TEXT PRIMARY KEY
///   name_en              TEXT
///   birthdate            TEXT
///   birthdate_precision  INTEGER
///   birth_year           INTEGER
///   deathdate            TEXT
///   deathdate_precision  INTEGER
///   death_year           INTEGER
///   floruit_date         TEXT
///   floruit_precision    INTEGER
///   floruit_year         INTEGER
///   floruit_period       TEXT     -- "1880-1905" / "12th c. AD"
///   floruit_period_start INTEGER
///   floruit_period_end   INTEGER
///   method               TEXT     -- see priority list below
///   precision_class      TEXT     -- 'year' / 'decade' / 'century' / 'polity'
///
/// Priority order (first applicable wins; methods are mutually exclusive):
///   1. floruit          - P1317 at year/decade precision
///   2. birth            - P569 year/decade (with optional P570)
///   3. death            - P570 year/decade only
///   4. desc_range       - description has both birth AND death year
///   5. desc_floruit     - description has fl/active/exhibited year (or BC/AD marker)
///   6. desc_birth       - description has b/born/baptized year only
///   7. desc_death       - description has d/died/buried year only
///   8. floruit_century  - P1317 at century precision
///   9. birth_century    - P569 at century precision
///   10. death_century   - P570 at century precision (no birth_century)
///   11. desc_century    - century token (c19, c4 BC) in dates_in_description
///   12. polity_only     - cliopatria-matched polity is dated, no other signal
///
/// Year period: ages 30..=55 (default span 25 years), capped by death.
/// Death-only: 25 years before death.
/// Polity-only: spans the polity's full lifetime (min from_year .. max to_year).
///
/// Precision codes (Wikidata): 11=day, 10=month, 9=year, 8=decade, 7=century.
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
        let n = (year + 99) / 100;
        format!("{} c. AD", ordinal(n as u64))
    } else if year < 0 {
        let n = (-year + 99) / 100;
        format!("{} c. BC", ordinal(n as u64))
    } else {
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

/// Classify the kinds of tokens present in `dates_in_description` so we can
/// pick the right desc_* method.
#[derive(Default, Debug, Clone)]
struct DescTokens {
    has_b: bool,
    has_d: bool,
    has_fl: bool,
    has_range: bool,
    has_marker: bool,   // BC/AD year (e.g. "199 BC")
    has_century: bool,  // century token "c19", "c4 BC"
    century_year: Option<i64>, // signed midpoint year of the first century token
}

fn classify_desc(raw: &str) -> DescTokens {
    let mut t = DescTokens::default();
    if raw.is_empty() {
        return t;
    }
    for tok in raw.split('|').map(|s| s.trim()).filter(|s| !s.is_empty()) {
        if let Some(rest) = tok.strip_prefix("b ") {
            if rest.parse::<i64>().is_ok() {
                t.has_b = true;
                continue;
            }
        }
        if let Some(rest) = tok.strip_prefix("d ") {
            if rest.parse::<i64>().is_ok() {
                t.has_d = true;
                continue;
            }
        }
        if let Some(rest) = tok.strip_prefix("fl ") {
            if rest.parse::<i64>().is_ok() {
                t.has_fl = true;
                continue;
            }
        }
        if let Some(rest) = tok.strip_prefix('c') {
            // "c19" or "c19 BC" or "c19 AD"
            let mut parts = rest.splitn(2, ' ');
            if let Some(num_str) = parts.next() {
                if let Ok(n) = num_str.parse::<u32>() {
                    if (1..=25).contains(&n) {
                        let marker = parts.next().unwrap_or("").trim();
                        let is_bc = matches!(marker, "BC" | "BCE" | "AC");
                        let mid = (n as i64 - 1) * 100 + 50;
                        let signed = if is_bc { -mid } else { mid };
                        t.has_century = true;
                        if t.century_year.is_none() {
                            t.century_year = Some(signed);
                        }
                        continue;
                    }
                }
            }
        }
        // BC/AD bare year, e.g. "199 BC", "10 AD"
        let mut parts = tok.splitn(2, ' ');
        let num_part = parts.next().unwrap_or("");
        let mark_part = parts.next().unwrap_or("").trim();
        if matches!(mark_part, "BC" | "BCE" | "AC" | "AD" | "CE") {
            if num_part.parse::<i64>().is_ok() {
                t.has_marker = true;
                continue;
            }
        }
        // YYYY-YYYY range
        if let Some((a, b)) = tok.split_once('-') {
            if a.parse::<i64>().is_ok() && b.parse::<i64>().is_ok() {
                t.has_range = true;
                continue;
            }
        }
        // -YYYY-YYYY (BC range, parse as range too)
        if tok.starts_with('-') {
            let inner = &tok[1..];
            if let Some((a, b)) = inner.split_once('-') {
                if a.parse::<i64>().is_ok() && b.parse::<i64>().is_ok() {
                    t.has_range = true;
                    continue;
                }
            }
        }
    }
    t
}

#[derive(Default, Debug)]
struct Stats {
    total: i64,
    floruit: i64,
    birth: i64,
    death: i64,
    desc_range: i64,
    desc_floruit: i64,
    desc_birth: i64,
    desc_death: i64,
    floruit_century: i64,
    birth_century: i64,
    death_century: i64,
    desc_century: i64,
    polity_only: i64,
    no_period: i64,
    contradicted: i64,
}

fn main() -> Result<()> {
    let total_start = Instant::now();
    log("=== Step 60: Build individuals_floruit_period (with description + polity fallback) ===");

    let conn = Connection::open(DB_PATH).context("opening database")?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // ---- Pre-load polity-period bounds: polity_id -> (min_from_year, max_to_year)
    log("[60] Loading polity period bounds...");
    let mut polity_bounds: HashMap<i64, (i64, i64)> = HashMap::new();
    {
        let mut s = conn.prepare(
            "SELECT polity_id, MIN(from_year), MAX(to_year)
             FROM polities_periods_cliopatria
             WHERE from_year IS NOT NULL AND to_year IS NOT NULL
             GROUP BY polity_id",
        )?;
        let rows = s.query_map([], |r| {
            Ok((r.get::<_, i64>(0)?, r.get::<_, i64>(1)?, r.get::<_, i64>(2)?))
        })?;
        for row in rows {
            let (pid, fy, ty) = row?;
            polity_bounds.insert(pid, (fy, ty));
        }
    }
    log(&format!("[60] Loaded {} dated polities", polity_bounds.len()));

    // ---- Pre-load wikidata_id -> polity_id (any one entry per individual)
    log("[60] Loading individual-polity mapping...");
    let mut individual_polity: HashMap<String, i64> = HashMap::new();
    {
        let mut s = conn.prepare(
            "SELECT wikidata_id, polity_id FROM individuals_cliopatria
             WHERE polity_id IS NOT NULL",
        )?;
        let rows = s.query_map([], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
        })?;
        for row in rows {
            let (qid, pid_s) = row?;
            if let Ok(pid) = pid_s.parse::<i64>() {
                individual_polity.entry(qid).or_insert(pid);
            }
        }
    }
    log(&format!("[60] Loaded {} individual-polity mappings", individual_polity.len()));

    // ---- Recreate destination table.
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
            floruit_period_start INTEGER,
            floruit_period_end   INTEGER,
            method               TEXT,
            precision_class      TEXT
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
            "SELECT wikidata_id, name_en,
                    birthdate, birthdate_precision,
                    deathdate, deathdate_precision,
                    floruit_date, floruit_precision, floruit_year,
                    birthdate_in_description,
                    deathdate_in_description,
                    floruit_year_in_description,
                    dates_in_description
             FROM individuals",
        )?;
        let mut ins = tx.prepare(
            "INSERT INTO individuals_floruit_period (
                wikidata_id, name_en,
                birthdate, birthdate_precision, birth_year,
                deathdate, deathdate_precision, death_year,
                floruit_date, floruit_precision, floruit_year,
                floruit_period, floruit_period_start, floruit_period_end,
                method, precision_class
            ) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16)",
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
            let fdate: Option<String> = row.get(6)?;
            let fprec: Option<i64> = row.get(7)?;
            let fyear: Option<i64> = row.get(8)?;
            let desc_b: Option<i64> = row.get(9)?;
            let desc_d: Option<i64> = row.get(10)?;
            let desc_fl: Option<i64> = row.get(11)?;
            let desc_raw: Option<String> = row.get(12)?;

            let mut birth_year = birthdate.as_deref().and_then(parse_year);
            let mut death_year = deathdate.as_deref().and_then(parse_year);

            if let (Some(b), Some(d)) = (birth_year, death_year) {
                if b > d {
                    stats.contradicted += 1;
                    death_year = None;
                }
            }

            // Compute primary (Wikidata-only) tier first.
            let (start, end, method, prec_class) = compute_floruit(
                birth_year, bprec,
                death_year, dprec,
                fyear,      fprec,
            );

            // Description fallback (only if Wikidata gave no period).
            let (start, end, method, prec_class): (Option<i64>, Option<i64>, String, String) =
                if !method.is_empty() {
                    (start, end, method.to_string(), prec_class.to_string())
                } else {
                    let desc_tokens = desc_raw.as_deref().map(classify_desc).unwrap_or_default();
                    let (s, e, m, p) = compute_desc_floruit(desc_b, desc_d, desc_fl, &desc_tokens);
                    (s, e, m.to_string(), p.to_string())
                };

            // Polity-only residual (only if everything else gave nothing).
            let (start, end, method, prec_class) = if !method.is_empty() {
                (start, end, method, prec_class)
            } else if let Some(pid) = individual_polity.get(&qid) {
                if let Some(&(fy, ty)) = polity_bounds.get(pid) {
                    (Some(fy), Some(ty), "polity_only".to_string(), "polity".to_string())
                } else {
                    (None, None, String::new(), String::new())
                }
            } else {
                (None, None, String::new(), String::new())
            };

            match method.as_str() {
                "floruit" => stats.floruit += 1,
                "birth" => stats.birth += 1,
                "death" => stats.death += 1,
                "desc_range" => stats.desc_range += 1,
                "desc_floruit" => stats.desc_floruit += 1,
                "desc_birth" => stats.desc_birth += 1,
                "desc_death" => stats.desc_death += 1,
                "floruit_century" => stats.floruit_century += 1,
                "birth_century" => stats.birth_century += 1,
                "death_century" => stats.death_century += 1,
                "desc_century" => stats.desc_century += 1,
                "polity_only" => stats.polity_only += 1,
                _ => stats.no_period += 1,
            }

            // Display formatting: period string.
            let century_display = matches!(
                method.as_str(),
                "floruit_century" | "birth_century" | "death_century" | "desc_century"
            );
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
                start,
                end,
                if method.is_empty() { None } else { Some(&method) },
                if prec_class.is_empty() { None } else { Some(&prec_class) },
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
         CREATE INDEX IF NOT EXISTS idx_fp_precision     ON individuals_floruit_period(precision_class);
         CREATE INDEX IF NOT EXISTS idx_fp_birth_year    ON individuals_floruit_period(birth_year);
         CREATE INDEX IF NOT EXISTS idx_fp_death_year    ON individuals_floruit_period(death_year);",
    )?;
    log(&format!("[60] Indexes created ({})", elapsed(idx)));

    log("[60] === Summary ===");
    log(&format!("[60]   total rows:          {}", stats.total));
    log(&format!("[60]   floruit:             {}", stats.floruit));
    log(&format!("[60]   birth:               {}", stats.birth));
    log(&format!("[60]   death:               {}", stats.death));
    log(&format!("[60]   desc_range:          {}", stats.desc_range));
    log(&format!("[60]   desc_floruit:        {}", stats.desc_floruit));
    log(&format!("[60]   desc_birth:          {}", stats.desc_birth));
    log(&format!("[60]   desc_death:          {}", stats.desc_death));
    log(&format!("[60]   floruit_century:     {}", stats.floruit_century));
    log(&format!("[60]   birth_century:       {}", stats.birth_century));
    log(&format!("[60]   death_century:       {}", stats.death_century));
    log(&format!("[60]   desc_century:        {}", stats.desc_century));
    log(&format!("[60]   polity_only:         {}", stats.polity_only));
    log(&format!("[60]   no_period:           {}", stats.no_period));
    log(&format!("[60]   contradicted dropped:{}", stats.contradicted));

    log(&format!(
        "=== Step 60 complete (total: {}) ===",
        elapsed(total_start)
    ));
    Ok(())
}

/// Wikidata-only tier. Returns ("", "") when no signal is usable.
fn compute_floruit(
    birth_year: Option<i64>,
    birth_prec: Option<i64>,
    death_year: Option<i64>,
    death_prec: Option<i64>,
    floruit_year: Option<i64>,
    floruit_prec: Option<i64>,
) -> (Option<i64>, Option<i64>, &'static str, &'static str) {
    let year_precise = |p: Option<i64>| matches!(p, Some(x) if x >= 9);
    let decade_precise = |p: Option<i64>| matches!(p, Some(x) if x >= 8);
    let century_precise = |p: Option<i64>| matches!(p, Some(x) if (5..=7).contains(&x));

    let prec_of = |a: Option<i64>, b: Option<i64>| -> &'static str {
        let useful = match (a, b) {
            (Some(x), Some(y)) => Some(x.min(y)),
            (Some(x), None) => Some(x),
            (None, Some(y)) => Some(y),
            (None, None) => None,
        };
        match useful {
            Some(x) if x >= 9 => "year",
            Some(8) => "decade",
            _ => "year",
        }
    };

    let birth_usable = birth_year.is_some() && decade_precise(birth_prec);
    let death_usable = death_year.is_some() && decade_precise(death_prec);
    let floruit_year_usable = floruit_year.is_some() && decade_precise(floruit_prec);

    // 1. P1317 floruit at year/decade.
    if floruit_year_usable {
        let fy = floruit_year.unwrap();
        let mut end = fy + FLORUIT_SPAN;
        if death_usable {
            let d = death_year.unwrap();
            if d < end { end = d; }
        }
        let end = end.min(CURRENT_YEAR);
        let start = fy.min(end);
        let pc = if year_precise(floruit_prec) { "year" } else { "decade" };
        return (Some(start), Some(end), "floruit", pc);
    }

    // 2. birth + death.
    if birth_usable && death_usable {
        let b = birth_year.unwrap();
        let d = death_year.unwrap();
        if b + FLORUIT_LO_OFFSET > CURRENT_YEAR {
            return (None, None, "", "");
        }
        let start = b + FLORUIT_LO_OFFSET;
        let end = (b + FLORUIT_HI_OFFSET).min(d).min(CURRENT_YEAR);
        let pc = prec_of(birth_prec, death_prec);
        if start <= end {
            return (Some(start), Some(end), "birth", pc);
        }
        let end = d.min(CURRENT_YEAR);
        return (Some(end.min(start)), Some(end), "birth", pc);
    }

    // 3. only birth.
    if birth_usable && !death_usable {
        let b = birth_year.unwrap();
        if b + FLORUIT_LO_OFFSET > CURRENT_YEAR {
            return (None, None, "", "");
        }
        let start = b + FLORUIT_LO_OFFSET;
        let end = (b + FLORUIT_HI_OFFSET).min(CURRENT_YEAR);
        let pc = prec_of(birth_prec, None);
        return (Some(start.min(end)), Some(end), "birth", pc);
    }

    // 4. only death.
    if death_usable && !birth_usable {
        let d = death_year.unwrap();
        let end = d.min(CURRENT_YEAR);
        let start = end - DEATH_ONLY_LOOKBACK;
        let pc = prec_of(death_prec, None);
        return (Some(start), Some(end), "death", pc);
    }

    // 8. floruit_century.
    if let Some(fy) = floruit_year {
        if century_precise(floruit_prec) {
            return (Some(fy), Some(fy), "floruit_century", "century");
        }
    }

    // 9. birth_century (extends to death_century if also century).
    if let Some(by) = birth_year {
        if century_precise(birth_prec) {
            let end = match (death_year, death_prec) {
                (Some(dy), dp) if century_precise(dp) && dy >= by => dy,
                _ => by,
            };
            return (Some(by), Some(end), "birth_century", "century");
        }
    }

    // 10. death_century only.
    if let Some(dy) = death_year {
        if century_precise(death_prec) {
            return (Some(dy), Some(dy), "death_century", "century");
        }
    }

    (None, None, "", "")
}

/// Description-derived tier. Only invoked when Wikidata produced no period.
fn compute_desc_floruit(
    desc_b: Option<i64>,
    desc_d: Option<i64>,
    desc_fl: Option<i64>,
    tokens: &DescTokens,
) -> (Option<i64>, Option<i64>, &'static str, &'static str) {
    // 4. range (b AND d both extracted from description).
    if let (Some(b), Some(d)) = (desc_b, desc_d) {
        if b <= d && b + FLORUIT_LO_OFFSET <= CURRENT_YEAR {
            let start = b + FLORUIT_LO_OFFSET;
            let end = (b + FLORUIT_HI_OFFSET).min(d).min(CURRENT_YEAR);
            return (Some(start.min(end)), Some(end), "desc_range", "year");
        }
    }

    // 5. fl from description (or BC/AD marker captured into floruit_year_in_description).
    if let Some(fy) = desc_fl {
        // Keep only fl/marker signals here; range-derived midpoints are handled above.
        if tokens.has_fl || tokens.has_marker {
            let mut end = fy + FLORUIT_SPAN;
            if let Some(d) = desc_d {
                if d < end { end = d; }
            }
            let end = end.min(CURRENT_YEAR);
            let start = fy.min(end);
            return (Some(start), Some(end), "desc_floruit", "year");
        }
    }

    // 6. b only (from description).
    if let Some(b) = desc_b {
        if b + FLORUIT_LO_OFFSET <= CURRENT_YEAR {
            let start = b + FLORUIT_LO_OFFSET;
            let end = (b + FLORUIT_HI_OFFSET).min(CURRENT_YEAR);
            return (Some(start.min(end)), Some(end), "desc_birth", "year");
        }
    }

    // 7. d only (from description).
    if let Some(d) = desc_d {
        let end = d.min(CURRENT_YEAR);
        let start = end - DEATH_ONLY_LOOKBACK;
        return (Some(start), Some(end), "desc_death", "year");
    }

    // 11. desc_century — pure century token, no other year-precision signal.
    if tokens.has_century {
        if let Some(cy) = tokens.century_year {
            // Use the century containing cy as the period.
            let (lo, hi) = if cy >= 0 {
                let n = (cy - 1) / 100; // 0-indexed century
                (n * 100 + 1, (n + 1) * 100)
            } else {
                let n = (-cy - 1) / 100;
                (-((n + 1) * 100), -(n * 100 + 1))
            };
            return (Some(lo), Some(hi), "desc_century", "century");
        }
    }

    (None, None, "", "")
}
