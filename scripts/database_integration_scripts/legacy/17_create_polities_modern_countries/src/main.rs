// Build the `polities_modern_countries_cliopatria` table by joining
// polities_cliopatria.wikidata_id to the JSON produced by
// scripts/wikidata_extraction_scripts_v2/17_extract_polity_modern_countries.py.
//
// Per row: (polity_id, country_qid, country_name, iso_a3_code, source).
// (polity_id, country_qid, source) is the natural key — keeping `source`
// in the PK lets us preserve which Wikidata pattern produced the link.
//
// Country names are looked up from the existing `modern_countries.json`
// pull (English label) when available; otherwise NULL.

use anyhow::{Context, Result};
use chrono::Local;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection, OpenFlags};
use serde_json::Value;
use std::collections::HashMap;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::time::Instant;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const POLITY_COUNTRIES_PATH: &str =
    "data/all_humans/wikidata_extraction_scripts_v2/polity_modern_countries.json";
// V2 pull lives under all_humans/; older one at all_humans/modern_countries.json.
// We try the V2 file first, then fall back.
const COUNTRIES_PATH_V2: &str =
    "data/all_humans/wikidata_extraction_scripts_v2/modern_countries.json";
const COUNTRIES_PATH_FALLBACK: &str = "data/all_humans/modern_countries.json";
const LOG_PATH: &str = "logs/17_create_polities_modern_countries.log";
const TASK_LOG: &str = "task.log";

fn log_line(log: &mut std::fs::File, task_log: &mut std::fs::File, msg: &str) {
    let stamped = format!("[{}] [17-rs] {}", Local::now().format("%Y-%m-%d %H:%M:%S"), msg);
    println!("{stamped}");
    let _ = writeln!(log, "{stamped}");
    let _ = log.flush();
    let _ = writeln!(task_log, "{stamped}");
    let _ = task_log.flush();
}

fn read_json(path: &str) -> Result<Value> {
    let f = std::fs::File::open(path).with_context(|| format!("opening {path}"))?;
    let v: Value = serde_json::from_reader(std::io::BufReader::new(f))
        .with_context(|| format!("parsing {path}"))?;
    Ok(v)
}

fn main() -> Result<()> {
    if !Path::new(DB_PATH).exists() {
        anyhow::bail!("DB not found at {DB_PATH}. Run from project root.");
    }
    std::fs::create_dir_all("logs").ok();
    let mut log = OpenOptions::new()
        .create(true)
        .append(true)
        .open(LOG_PATH)
        .with_context(|| format!("opening log {LOG_PATH}"))?;
    let mut task_log = OpenOptions::new()
        .create(true)
        .append(true)
        .open(TASK_LOG)
        .with_context(|| format!("opening {TASK_LOG}"))?;

    log_line(&mut log, &mut task_log, "=== 17_create_polities_modern_countries START ===");

    // --- 1. Load JSON inputs ---
    log_line(&mut log, &mut task_log, &format!("loading {POLITY_COUNTRIES_PATH}"));
    let pc_v = read_json(POLITY_COUNTRIES_PATH)?;
    let pc = pc_v.as_object().context("polity_modern_countries.json is not an object")?;
    log_line(&mut log, &mut task_log, &format!("  {} polity entries", pc.len()));

    let countries_path = if Path::new(COUNTRIES_PATH_V2).exists() {
        COUNTRIES_PATH_V2
    } else {
        COUNTRIES_PATH_FALLBACK
    };
    log_line(&mut log, &mut task_log, &format!("loading {countries_path} for English labels"));
    let countries_v = read_json(countries_path)?;
    let countries = countries_v
        .as_object()
        .context("modern_countries.json is not an object")?;
    let mut country_name: HashMap<String, String> = HashMap::with_capacity(countries.len());
    let mut country_continent: HashMap<String, String> = HashMap::with_capacity(countries.len());
    for (qid, rec) in countries {
        if let Some(name) = rec.get("name").and_then(|v| v.as_str()) {
            country_name.insert(qid.clone(), name.to_string());
        }
        if let Some(cont) = rec.get("continent").and_then(|v| v.as_str()) {
            country_continent.insert(qid.clone(), cont.to_string());
        }
    }
    log_line(
        &mut log,
        &mut task_log,
        &format!(
            "  {} country labels, {} continents available",
            country_name.len(),
            country_continent.len()
        ),
    );

    // --- 2. Open DB, build polity wikidata_id -> id map ---
    let conn = Connection::open_with_flags(
        DB_PATH,
        OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .with_context(|| format!("opening {DB_PATH}"))?;
    conn.pragma_update(None, "journal_mode", "WAL")?;
    conn.pragma_update(None, "synchronous", "NORMAL")?;
    conn.pragma_update(None, "temp_store", "MEMORY")?;
    conn.pragma_update(None, "cache_size", -1_000_000)?;

    // QIDs are not unique across polities_cliopatria (e.g. multiple "city
    // states" rows pointing at the same Wikidata entity). Map QID -> all
    // (polity_id, polity_name) so every row inherits the country list and
    // carries its own name.
    let mut polity_map: HashMap<String, Vec<(i64, String)>> = HashMap::new();
    let mut polity_qid_rows: i64 = 0;
    {
        let mut stmt = conn.prepare(
            "SELECT id, name, wikidata_id FROM polities_cliopatria
             WHERE wikidata_id IS NOT NULL AND wikidata_id != ''",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?))
        })?;
        for row in rows {
            let (id, name, qid) = row?;
            polity_map.entry(qid).or_default().push((id, name));
            polity_qid_rows += 1;
        }
    }
    log_line(
        &mut log,
        &mut task_log,
        &format!(
            "polity_map: {} unique QIDs covering {} polity rows",
            polity_map.len(),
            polity_qid_rows
        ),
    );

    // --- 3. Recreate the table ---
    log_line(&mut log, &mut task_log, "DROP/CREATE polities_modern_countries_cliopatria");
    conn.execute_batch(
        "DROP TABLE IF EXISTS polities_modern_countries_cliopatria;
         CREATE TABLE polities_modern_countries_cliopatria (
             polity_id    INTEGER NOT NULL,
             polity_name  TEXT    NOT NULL,
             country_qid  TEXT    NOT NULL,
             country_name TEXT,
             iso_a3_code  TEXT    NOT NULL,
             continent    TEXT,
             sources      TEXT    NOT NULL,  -- pipe-joined, sorted
             PRIMARY KEY (polity_id, country_qid),
             FOREIGN KEY (polity_id) REFERENCES polities_cliopatria(id)
         );
         CREATE INDEX idx_pmcc_polity ON polities_modern_countries_cliopatria(polity_id);
         CREATE INDEX idx_pmcc_polity_name ON polities_modern_countries_cliopatria(polity_name);
         CREATE INDEX idx_pmcc_country ON polities_modern_countries_cliopatria(country_qid);
         CREATE INDEX idx_pmcc_iso3 ON polities_modern_countries_cliopatria(iso_a3_code);
         CREATE INDEX idx_pmcc_continent ON polities_modern_countries_cliopatria(continent);",
    )?;

    // --- 4. Insert ---
    let total_links: usize = pc
        .values()
        .filter_map(|v| v.get("countries").and_then(|c| c.as_array()))
        .map(|a| a.len())
        .sum();
    let pb = ProgressBar::new(total_links as u64);
    pb.set_style(
        ProgressStyle::with_template("inserting: {pos}/{len} ({percent}%) ETA {eta}").unwrap(),
    );

    // Collapse (polity_id, country_qid) → set of sources before insert.
    use std::collections::BTreeSet;
    type Key = (i64, String);
    struct Entry {
        polity_name: String,
        country_qid: String,
        country_name: Option<String>,
        iso3: String,
        continent: Option<String>,
        sources: BTreeSet<String>,
    }
    let mut collapsed: HashMap<Key, Entry> = HashMap::new();
    let mut skipped_no_polity: u64 = 0;

    for (polity_qid, rec) in pc {
        let polity_rows = match polity_map.get(polity_qid) {
            Some(rows) => rows,
            None => {
                skipped_no_polity += 1;
                continue;
            }
        };
        let arr = match rec.get("countries").and_then(|c| c.as_array()) {
            Some(a) => a,
            None => continue,
        };
        for entry in arr {
            let cqid = entry.get("country_qid").and_then(|v| v.as_str()).unwrap_or("");
            let iso3 = entry.get("iso_a3_code").and_then(|v| v.as_str()).unwrap_or("");
            let src = entry.get("source").and_then(|v| v.as_str()).unwrap_or("");
            if cqid.is_empty() || iso3.is_empty() || src.is_empty() {
                continue;
            }
            let cname = country_name.get(cqid).cloned();
            let cont = country_continent.get(cqid).cloned();
            for (pid, pname) in polity_rows {
                let key: Key = (*pid, cqid.to_string());
                let e = collapsed.entry(key).or_insert_with(|| Entry {
                    polity_name: pname.clone(),
                    country_qid: cqid.to_string(),
                    country_name: cname.clone(),
                    iso3: iso3.to_string(),
                    continent: cont.clone(),
                    sources: BTreeSet::new(),
                });
                e.sources.insert(src.to_string());
            }
        }
    }

    let started = Instant::now();
    let mut inserted: u64 = 0;
    let tx = conn.unchecked_transaction()?;
    {
        let mut stmt = tx.prepare_cached(
            "INSERT INTO polities_modern_countries_cliopatria
                 (polity_id, polity_name, country_qid, country_name, iso_a3_code, continent, sources)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
        )?;
        for ((pid, _), e) in &collapsed {
            let sources_joined = e.sources.iter().cloned().collect::<Vec<_>>().join("|");
            stmt.execute(params![
                pid,
                e.polity_name,
                e.country_qid,
                e.country_name,
                e.iso3,
                e.continent,
                sources_joined
            ])?;
            inserted += 1;
            if inserted % 500 == 0 {
                pb.set_position(inserted);
            }
        }
    }
    tx.commit()?;
    pb.finish_and_clear();

    let total_in_db: i64 = conn.query_row(
        "SELECT COUNT(*) FROM polities_modern_countries_cliopatria",
        [],
        |r| r.get(0),
    )?;
    let polities_with_country: i64 = conn.query_row(
        "SELECT COUNT(DISTINCT polity_id) FROM polities_modern_countries_cliopatria",
        [],
        |r| r.get(0),
    )?;

    log_line(
        &mut log,
        &mut task_log,
        &format!(
            "DONE inserted={inserted} table_rows={total_in_db} polities_with_country={polities_with_country} \
             skipped_no_polity={skipped_no_polity} elapsed={:.1}s",
            started.elapsed().as_secs_f64()
        ),
    );
    log_line(&mut log, &mut task_log, "=== 17_create_polities_modern_countries END ===");
    Ok(())
}
