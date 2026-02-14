use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{Connection, params};
use serde::Deserialize;
use std::collections::HashMap;
use std::fs::File;
use std::io::BufReader;

#[derive(Debug, Deserialize)]
#[serde(untagged)]
enum SitelinkEntry {
    Url(String),
    Full { site: String, title: String, url: String },
}

fn parse_url_to_sitelink(url: &str) -> (String, String, String) {
    // Extract site from URL (e.g., "en.wikipedia.org")
    let site = if url.contains("//") {
        url.split("//").nth(1).unwrap_or("").split('/').next().unwrap_or("")
    } else {
        ""
    };

    // Extract title from URL (last path component, URL decoded)
    let title = url.rsplit('/').next().unwrap_or("");
    let title = urlencoding::decode(title).unwrap_or_else(|_| title.to_string());

    (site.to_string(), title, url.to_string())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let base_path = std::env::current_dir()?
        .parent().unwrap()
        .parent().unwrap()
        .to_path_buf();

    let json_path = base_path.join("data/all_humans/all_human_sitelinks.json");
    let db_path = base_path.join("data/humans_clean.sqlite3");

    println!("Loading sitelinks from: {:?}", json_path);
    println!("Database: {:?}", db_path);

    // Load JSON
    println!("\nReading JSON file...");
    let file = File::open(&json_path)?;
    let reader = BufReader::new(file);
    let data: HashMap<String, Vec<SitelinkEntry>> = serde_json::from_reader(reader)?;

    let total_individuals = data.len();
    let total_sitelinks: usize = data.values().map(|v| v.len()).sum();
    println!("Loaded {} individuals with {} sitelinks", total_individuals, total_sitelinks);

    // Connect to database
    let mut conn = Connection::open(&db_path)?;

    // Drop and recreate sitelinks table
    println!("\nCreating sitelinks table...");
    conn.execute("DROP TABLE IF EXISTS sitelinks", [])?;
    conn.execute(
        "CREATE TABLE sitelinks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wikidata_id TEXT NOT NULL,
            site TEXT,
            title TEXT,
            url TEXT
        )",
        [],
    )?;

    // Insert in batches with transaction
    println!("Inserting sitelinks...");
    let pb = ProgressBar::new(total_sitelinks as u64);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{spinner:.green} [{elapsed_precise}] [{bar:40.cyan/blue}] {pos}/{len} ({per_sec}) ETA: {eta}")?
            .progress_chars("=>-"),
    );

    let tx = conn.transaction()?;
    {
        let mut stmt = tx.prepare(
            "INSERT INTO sitelinks (wikidata_id, site, title, url) VALUES (?1, ?2, ?3, ?4)"
        )?;

        for (wikidata_id, sitelinks) in &data {
            for entry in sitelinks {
                let (site, title, url) = match entry {
                    SitelinkEntry::Url(url) => parse_url_to_sitelink(url),
                    SitelinkEntry::Full { site, title, url } => (site.clone(), title.clone(), url.clone()),
                };
                stmt.execute(params![wikidata_id, site, title, url])?;
                pb.inc(1);
            }
        }
    }
    tx.commit()?;
    pb.finish_with_message("Done!");

    // Create index after insert for better performance
    println!("\nCreating index...");
    conn.execute("CREATE INDEX idx_sitelinks_wikidata_id ON sitelinks(wikidata_id)", [])?;

    // Update sitelinks_count in individuals table
    println!("Updating sitelinks_count in individuals table...");
    conn.execute(
        "UPDATE individuals SET sitelinks_count = (
            SELECT COUNT(*) FROM sitelinks WHERE sitelinks.wikidata_id = individuals.wikidata_id
        )",
        [],
    )?;

    // Verify
    let count: i64 = conn.query_row("SELECT COUNT(*) FROM sitelinks", [], |row| row.get(0))?;
    let unique: i64 = conn.query_row("SELECT COUNT(DISTINCT wikidata_id) FROM sitelinks", [], |row| row.get(0))?;

    println!("\n{}", "=".repeat(60));
    println!("LOAD COMPLETE");
    println!("{}", "=".repeat(60));
    println!("Total sitelinks inserted: {}", count);
    println!("Unique individuals: {}", unique);

    Ok(())
}

mod urlencoding {
    pub fn decode(s: &str) -> Result<String, ()> {
        let mut result = String::new();
        let mut chars = s.chars().peekable();

        while let Some(c) = chars.next() {
            if c == '%' {
                let hex: String = chars.by_ref().take(2).collect();
                if hex.len() == 2 {
                    if let Ok(byte) = u8::from_str_radix(&hex, 16) {
                        result.push(byte as char);
                    } else {
                        result.push('%');
                        result.push_str(&hex);
                    }
                } else {
                    result.push('%');
                    result.push_str(&hex);
                }
            } else if c == '+' {
                result.push(' ');
            } else {
                result.push(c);
            }
        }
        Ok(result)
    }
}
