/// Path A — step 5.
///
/// MERGE the newly-extracted external-ID rows into the existing
/// `identifiers` table. The TSV produced by script 48 contains only
/// (wikidata_id, property_id, value) rows for properties that were
/// MISSING from the local DB — existing rows are NOT touched.
///
/// Steps:
///   1. Stream the TSV into `identifiers` with INSERT OR IGNORE.
///      Existing rows survive untouched.
///   2. Update `identifier_types` with one row per NEW property,
///      using labels and formatter URLs from
///      `data/all_humans/all_external_id_properties.json`.
///   3. Backfill `identifiers.individual_name` for the new rows from
///      `individuals.name_en`.
///   4. Backfill `identifiers.identifier_name` for the new rows from
///      `identifier_types.name_en`.
///   5. Recompute `individuals.identifiers_count` and
///      `identifier_types.count` over the full table.
///   6. Email cdedampierre@bunka.ai with a summary.
use anyhow::Result;
use rusqlite::{params, Connection};
use serde::Deserialize;
use std::collections::HashMap;
use std::fs::{File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::process::Command;
use std::time::Instant;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const TSV_PATH: &str = "data/all_humans/all_human_identifiers_v2.tsv";
const PROP_LIST_PATH: &str = "data/all_humans/all_external_id_properties.json";
const TASK_LOG: &str = "task.log";
const BATCH: usize = 100_000;

#[derive(Deserialize)]
struct PropEntry {
    property_id: String,
    label: String,
    formatter_url: String,
}

#[derive(Deserialize)]
struct PropList {
    properties: Vec<PropEntry>,
}

fn log(msg: &str) {
    let stamped = format!(
        "[{}] {}",
        chrono::Local::now().format("%Y-%m-%d %H:%M:%S"),
        msg
    );
    println!("{}", stamped);
    if let Ok(mut f) = OpenOptions::new().append(true).create(true).open(TASK_LOG) {
        let _ = writeln!(f, "{}", stamped);
    }
}

fn send_email(subject: &str, body: &str) -> Result<()> {
    let py = format!(
        r#"
import smtplib, ssl
from email.message import EmailMessage
m = EmailMessage()
m['Subject'] = {subject:?}
m['From']    = 'cdedampierre@bunka.ai'
m['To']      = 'cdedampierre@bunka.ai'
m.set_content({body:?})
ctx = ssl.create_default_context()
with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=ctx) as s:
    s.login('cdedampierre@bunka.ai', 'pfau ippr pxpl dssd')
    s.send_message(m)
print('email sent')
"#,
        subject = subject,
        body = body,
    );
    let status = Command::new("python3").arg("-c").arg(&py).status()?;
    if !status.success() {
        log("[61] WARN: email send failed");
    }
    Ok(())
}

fn main() -> Result<()> {
    log("[61] merging new identifier rows into existing `identifiers` table");
    let t0 = Instant::now();

    let prop_json: PropList =
        serde_json::from_str(&std::fs::read_to_string(PROP_LIST_PATH)?)?;
    let prop_meta: HashMap<String, (String, String)> = prop_json
        .properties
        .into_iter()
        .map(|p| (p.property_id, (p.label, p.formatter_url)))
        .collect();
    log(&format!("[61] loaded metadata for {} properties", prop_meta.len()));

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL;
         PRAGMA synchronous=NORMAL;
         PRAGMA cache_size=-2000000;
         PRAGMA temp_store=MEMORY;",
    )?;

    let pre_n_rows: i64 = conn.query_row("SELECT COUNT(*) FROM identifiers", [], |r| r.get(0))?;
    let pre_n_props: i64 = conn.query_row(
        "SELECT COUNT(DISTINCT property_id) FROM identifiers",
        [],
        |r| r.get(0),
    )?;
    log(&format!(
        "[61] before merge: {} rows / {} distinct props",
        pre_n_rows, pre_n_props
    ));

    let f = File::open(TSV_PATH)?;
    let reader = BufReader::new(f);

    let mut tx = conn.unchecked_transaction()?;
    let mut buf: Vec<(String, String, String)> = Vec::with_capacity(BATCH);
    let mut total: u64 = 0;
    let mut header_skipped = false;

    let flush = |conn: &Connection, buf: &mut Vec<(String, String, String)>| -> Result<()> {
        let mut s = conn.prepare_cached(
            "INSERT OR IGNORE INTO identifiers (wikidata_id, property_id, value)
             VALUES (?1, ?2, ?3)",
        )?;
        for (q, p, v) in buf.drain(..) {
            s.execute(params![q, p, v])?;
        }
        Ok(())
    };

    for line in reader.lines() {
        let line = line?;
        if !header_skipped {
            header_skipped = true;
            continue;
        }
        let mut it = line.splitn(3, '\t');
        let qid = match it.next() {
            Some(s) => s.to_string(),
            None => continue,
        };
        let pid = match it.next() {
            Some(s) => s.to_string(),
            None => continue,
        };
        let value = match it.next() {
            Some(s) => s.to_string(),
            None => continue,
        };
        if !qid.starts_with('Q') || !pid.starts_with('P') {
            continue;
        }
        buf.push((qid, pid, value));
        if buf.len() >= BATCH {
            flush(&tx, &mut buf)?;
            total += BATCH as u64;
            if total % 5_000_000 == 0 {
                log(&format!("[61]   inserted {} rows so far", total));
                tx.commit()?;
                tx = conn.unchecked_transaction()?;
            }
        }
    }
    if !buf.is_empty() {
        let n = buf.len() as u64;
        flush(&tx, &mut buf)?;
        total += n;
    }
    tx.commit()?;
    log(&format!(
        "[61] streamed {} rows in {:.1}s",
        total,
        t0.elapsed().as_secs_f64()
    ));

    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_identifiers_wikidata ON identifiers(wikidata_id);
         CREATE INDEX IF NOT EXISTS idx_identifiers_property ON identifiers(property_id);
         CREATE INDEX IF NOT EXISTS idx_identifiers_name     ON identifiers(individual_name);",
    )?;

    log("[61] upserting identifier_types for new properties");
    {
        let mut stmt = conn.prepare(
            "INSERT INTO identifier_types
                (property_id, name_en, count, description, issuer_name, issuer_id,
                 issuer_instance, country_name, country_id, inception, database_records, website)
             VALUES (?1, ?2, 0, '', '', '', '', '', '', '', '', ?3)
             ON CONFLICT(property_id) DO UPDATE SET
                 name_en = CASE WHEN identifier_types.name_en IS NULL OR identifier_types.name_en = ''
                                THEN excluded.name_en ELSE identifier_types.name_en END,
                 website = CASE WHEN identifier_types.website IS NULL OR identifier_types.website = ''
                                THEN excluded.website ELSE identifier_types.website END",
        )?;
        let new_pids: Vec<String> = conn
            .prepare(
                "SELECT DISTINCT property_id FROM identifiers
                 WHERE property_id NOT IN (SELECT property_id FROM identifier_types)",
            )?
            .query_map([], |r| r.get::<_, String>(0))?
            .filter_map(|r| r.ok())
            .collect();
        log(&format!("[61]   new properties to register: {}", new_pids.len()));
        for pid in &new_pids {
            let (label, formatter) = prop_meta
                .get(pid)
                .cloned()
                .unwrap_or_else(|| (String::new(), String::new()));
            stmt.execute(params![pid, label, formatter])?;
        }
    }

    log("[61] backfilling identifiers.individual_name from individuals.name_en");
    conn.execute_batch(
        "UPDATE identifiers
            SET individual_name = (
                SELECT name_en FROM individuals
                WHERE individuals.wikidata_id = identifiers.wikidata_id
            )
            WHERE individual_name IS NULL OR individual_name = '';",
    )?;

    log("[61] backfilling identifiers.identifier_name from identifier_types.name_en");
    conn.execute_batch(
        "UPDATE identifiers
            SET identifier_name = (
                SELECT name_en FROM identifier_types
                WHERE identifier_types.property_id = identifiers.property_id
            )
            WHERE identifier_name IS NULL OR identifier_name = '';",
    )?;

    log("[61] recomputing individuals.identifiers_count");
    conn.execute_batch(
        "UPDATE individuals SET identifiers_count = (
             SELECT COUNT(*) FROM identifiers
             WHERE identifiers.wikidata_id = individuals.wikidata_id
         );",
    )?;

    log("[61] recomputing identifier_types.count");
    conn.execute_batch(
        "UPDATE identifier_types SET count = (
             SELECT COUNT(*) FROM identifiers
             WHERE identifiers.property_id = identifier_types.property_id
         );",
    )?;

    let post_n_rows: i64 = conn.query_row("SELECT COUNT(*) FROM identifiers", [], |r| r.get(0))?;
    let post_n_props: i64 = conn.query_row(
        "SELECT COUNT(DISTINCT property_id) FROM identifiers",
        [],
        |r| r.get(0),
    )?;
    let n_individuals_with_id: i64 = conn.query_row(
        "SELECT COUNT(*) FROM individuals WHERE identifiers_count > 0",
        [],
        |r| r.get(0),
    )?;
    let summary = format!(
        "Identifier merge complete.\n\
         Rows before:           {pre_rows}\n\
         Rows after:            {post_rows}  (delta {delta_rows:+})\n\
         Distinct props before: {pre_props}\n\
         Distinct props after:  {post_props}  (delta {delta_props:+})\n\
         Individuals with >=1 identifier: {with_id}\n\
         Wall time: {secs:.1}s",
        pre_rows = pre_n_rows,
        post_rows = post_n_rows,
        delta_rows = post_n_rows - pre_n_rows,
        pre_props = pre_n_props,
        post_props = post_n_props,
        delta_props = post_n_props - pre_n_props,
        with_id = n_individuals_with_id,
        secs = t0.elapsed().as_secs_f64(),
    );
    log(&format!("[61] {}", summary.replace('\n', " | ")));

    if let Err(e) = send_email("[cultura-database] Identifier merge complete", &summary) {
        log(&format!("[61] WARN: email failed: {}", e));
    }

    log("[61] DONE");
    Ok(())
}
