use regex::Regex;
use rusqlite::{Connection, params};
use serde::Deserialize;
use std::collections::HashMap;
use std::fs;
use std::thread;
use std::time::Duration;
use unicode_normalization::UnicodeNormalization;

#[derive(Debug, Deserialize)]
struct Nationality {
    id: String,
    name: String,
}

#[derive(Debug, Deserialize)]
struct WikidataSearchResult {
    search: Vec<WikidataSearchItem>,
}

#[derive(Debug, Deserialize)]
struct WikidataSearchItem {
    id: String,
    label: Option<String>,
}

fn normalize_string(s: &str) -> String {
    s.nfc().collect::<String>()
}

fn search_wikidata(name: &str) -> Option<String> {
    let url = format!(
        "https://www.wikidata.org/w/api.php?action=wbsearchentities&search={}&language=en&format=json",
        urlencoding::encode(name)
    );

    match ureq::get(&url).call() {
        Ok(response) => {
            if let Ok(result) = response.into_json::<WikidataSearchResult>() {
                if let Some(item) = result.search.first() {
                    return Some(item.id.clone());
                }
            }
        }
        Err(e) => {
            eprintln!("Error searching Wikidata for '{}': {}", name, e);
        }
    }
    None
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let base_path = std::env::current_dir()?
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .to_path_buf();

    let json_path = base_path.join("data/all_humans/all_human_nationalities.json");
    let db_path = base_path.join("data/humans_clean.sqlite3");

    println!("Loading JSON from: {:?}", json_path);
    println!("Database at: {:?}", db_path);

    // Load and parse JSON
    let json_content = fs::read_to_string(&json_path)?;
    let data: HashMap<String, Vec<Nationality>> = serde_json::from_str(&json_content)?;

    // Extract unique nationalities: name_en -> wikidata_id
    // Also create normalized version for fuzzy matching
    let name_pattern = Regex::new(r#""(.+)"@\w+"#)?;
    let mut nationality_map: HashMap<String, String> = HashMap::new();
    let mut normalized_map: HashMap<String, (String, String)> = HashMap::new(); // normalized -> (original, id)

    for nationalities in data.values() {
        for nat in nationalities {
            if let Some(caps) = name_pattern.captures(&nat.name) {
                let name_en = caps.get(1).unwrap().as_str().to_string();
                let normalized = normalize_string(&name_en);
                nationality_map.entry(name_en.clone()).or_insert_with(|| nat.id.clone());
                normalized_map.entry(normalized).or_insert_with(|| (name_en, nat.id.clone()));
            }
        }
    }

    println!("Found {} unique nationalities in JSON", nationality_map.len());

    // Connect to database
    let conn = Connection::open(&db_path)?;

    // Get nationalities with missing wikidata_id
    let mut stmt = conn.prepare(
        "SELECT name_en FROM nationalities WHERE wikidata_id IS NULL OR wikidata_id = ''"
    )?;

    let missing_names: Vec<String> = stmt
        .query_map([], |row| row.get(0))?
        .filter_map(|r| r.ok())
        .collect();

    println!("Found {} nationalities with missing wikidata_id in DB", missing_names.len());

    // Update missing entries
    let mut update_stmt = conn.prepare(
        "UPDATE nationalities SET wikidata_id = ? WHERE name_en = ?"
    )?;

    let mut fixed = 0;
    let mut fixed_normalized = 0;
    let mut still_missing = Vec::new();

    for name in &missing_names {
        // Try exact match first
        if let Some(wikidata_id) = nationality_map.get(name) {
            update_stmt.execute(params![wikidata_id, name])?;
            fixed += 1;
        } else {
            // Try normalized match
            let normalized = normalize_string(name);
            if let Some((_, wikidata_id)) = normalized_map.get(&normalized) {
                update_stmt.execute(params![wikidata_id, name])?;
                fixed_normalized += 1;
            } else {
                still_missing.push(name.clone());
            }
        }
    }

    println!("\nFixed {} nationalities (exact match)", fixed);
    println!("Fixed {} nationalities (normalized match)", fixed_normalized);
    println!("Still missing: {} nationalities", still_missing.len());

    // Now fetch remaining from Wikidata API
    if !still_missing.is_empty() {
        println!("\nFetching remaining {} from Wikidata API...", still_missing.len());
        let mut fetched = 0;
        let mut not_found = Vec::new();

        for name in &still_missing {
            if let Some(wikidata_id) = search_wikidata(name) {
                update_stmt.execute(params![wikidata_id, name])?;
                fetched += 1;
                println!("  Found: {} -> {}", name, wikidata_id);
            } else {
                not_found.push(name.clone());
            }
            // Rate limit: 200ms between requests
            thread::sleep(Duration::from_millis(200));
        }

        println!("\nFetched {} from Wikidata API", fetched);
        if !not_found.is_empty() {
            println!("Not found ({}):", not_found.len());
            for name in &not_found {
                println!("  - {}", name);
            }
        }
    }

    // Verify
    let count: i64 = conn.query_row(
        "SELECT COUNT(*) FROM nationalities WHERE wikidata_id IS NULL OR wikidata_id = ''",
        [],
        |row| row.get(0),
    )?;
    println!("\nRemaining without wikidata_id: {}", count);

    Ok(())
}

mod urlencoding {
    pub fn encode(s: &str) -> String {
        let mut result = String::new();
        for c in s.chars() {
            match c {
                'a'..='z' | 'A'..='Z' | '0'..='9' | '-' | '_' | '.' | '~' => result.push(c),
                ' ' => result.push_str("%20"),
                _ => {
                    for b in c.to_string().as_bytes() {
                        result.push_str(&format!("%{:02X}", b));
                    }
                }
            }
        }
        result
    }
}
