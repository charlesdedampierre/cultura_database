/// Create writing_languages table from extracted JSON data.
/// Creates both a reference table of languages and a mapping table.
use anyhow::Result;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{params, Connection};
use serde_json::Value;
use std::collections::HashMap;
use std::fs;
use std::io::Write;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const JSON_PATH: &str = "data/all_humans/all_human_writing_languages.json";
const TASK_LOG: &str = "task.log";

fn log(msg: &str) {
    println!("{}", msg);
    let mut f = fs::OpenOptions::new()
        .append(true)
        .open(TASK_LOG)
        .unwrap();
    writeln!(f, "{}", msg).unwrap();
}

fn clean_label(s: &str) -> String {
    let s = s.trim_matches('"');
    if s.ends_with("@en") {
        s[..s.len() - 3].to_string()
    } else {
        s.to_string()
    }
}

fn main() -> Result<()> {
    log("[DB] 08: Creating writing_languages table...");

    // Load writing languages JSON
    let json_str = fs::read_to_string(JSON_PATH)?;
    let human_langs: HashMap<String, Value> = serde_json::from_str(&json_str)?;
    log(&format!("[DB] Loaded writing languages for {} individuals", human_langs.len()));

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;")?;

    // Drop existing tables
    conn.execute_batch("DROP TABLE IF EXISTS writing_languages;")?;
    conn.execute_batch("DROP TABLE IF EXISTS individual_writing_languages;")?;

    // Create reference table for languages
    conn.execute_batch(
        "CREATE TABLE writing_languages (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            count INTEGER DEFAULT 0
        );"
    )?;

    // Create mapping table
    conn.execute_batch(
        "CREATE TABLE individual_writing_languages (
            wikidata_id TEXT NOT NULL,
            individual_name TEXT,
            language_id TEXT NOT NULL,
            language_name TEXT,
            PRIMARY KEY (wikidata_id, language_id)
        );"
    )?;

    // Collect all unique languages and build mapping data
    let mut lang_counts: HashMap<String, (String, i64)> = HashMap::new(); // id -> (name, count)
    let mut mappings: Vec<(String, String, String)> = Vec::new(); // (human_id, lang_id, lang_name)

    let pb = ProgressBar::new(human_langs.len() as u64);
    pb.set_style(ProgressStyle::default_bar()
        .template("{msg} [{bar:40}] {pos}/{len} ({eta})")
        .unwrap());
    pb.set_message("Processing languages");

    for (human_id, langs) in &human_langs {
        if let Some(arr) = langs.as_array() {
            for lang in arr {
                let lang_id = lang.get("id").and_then(|v| v.as_str()).unwrap_or_default().to_string();
                let lang_name = clean_label(lang.get("name").and_then(|v| v.as_str()).unwrap_or_default());

                if !lang_id.is_empty() && !lang_name.is_empty() {
                    let entry = lang_counts.entry(lang_id.clone()).or_insert((lang_name.clone(), 0));
                    entry.1 += 1;
                    mappings.push((human_id.clone(), lang_id, lang_name));
                }
            }
        }
        pb.inc(1);
    }
    pb.finish();

    log(&format!("[DB] Found {} unique languages, {} mappings", lang_counts.len(), mappings.len()));

    // Insert languages
    conn.execute_batch("BEGIN TRANSACTION;")?;
    {
        let mut stmt = conn.prepare("INSERT OR IGNORE INTO writing_languages (id, name, count) VALUES (?1, ?2, ?3)")?;
        for (id, (name, count)) in &lang_counts {
            stmt.execute(params![id, name, count])?;
        }
    }
    conn.execute_batch("COMMIT;")?;

    // Insert mappings in batches
    log("[DB] Inserting individual-language mappings...");
    let pb = ProgressBar::new(mappings.len() as u64);
    pb.set_style(ProgressStyle::default_bar()
        .template("{msg} [{bar:40}] {pos}/{len} ({per_sec}) ({eta})")
        .unwrap());
    pb.set_message("Inserting mappings");

    conn.execute_batch("BEGIN TRANSACTION;")?;
    let mut stmt = conn.prepare(
        "INSERT OR IGNORE INTO individual_writing_languages (wikidata_id, language_id, language_name) VALUES (?1, ?2, ?3)"
    )?;

    let mut batch_count = 0u64;
    for (human_id, lang_id, lang_name) in &mappings {
        stmt.execute(params![human_id, lang_id, lang_name])?;
        batch_count += 1;
        if batch_count % 100_000 == 0 {
            conn.execute_batch("COMMIT; BEGIN TRANSACTION;")?;
        }
        pb.inc(1);
    }
    conn.execute_batch("COMMIT;")?;
    pb.finish();

    // Update individual_name in the mapping table
    log("[DB] Updating individual names in writing_languages mapping...");
    conn.execute(
        "UPDATE individual_writing_languages SET individual_name = (
            SELECT individuals.name_en FROM individuals
            WHERE individuals.wikidata_id = individual_writing_languages.wikidata_id
        )",
        [],
    )?;

    // Create indexes
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_iwl_wikidata ON individual_writing_languages(wikidata_id);")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_iwl_lang ON individual_writing_languages(language_id);")?;

    log("[DB] 08: Done. Created writing_languages tables.");
    Ok(())
}
