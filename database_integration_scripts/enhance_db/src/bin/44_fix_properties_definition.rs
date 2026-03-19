/// Fix the properties_definition table.
/// Ensures all Wikidata properties used in the database are listed
/// with correct P-number, name, description, table, and column.
/// Removes properties not reflected in the database schema and adds missing ones.
use anyhow::Result;
use rusqlite::Connection;
use std::fs;
use std::io::Write;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const TASK_LOG: &str = "task.log";

fn log(msg: &str) {
    println!("{}", msg);
    let mut f = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(TASK_LOG)
        .unwrap();
    writeln!(f, "{}", msg).unwrap();
}

struct PropertyDef {
    property_id: &'static str,
    property_name: &'static str,
    description: &'static str,
    table_name: &'static str,
    column_name: &'static str,
}

fn main() -> Result<()> {
    log("=== Step 44: Fix properties_definition ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
    )?;

    // Show current state
    let current_count: i64 = conn.query_row(
        "SELECT COUNT(*) FROM properties_definition",
        [],
        |r| r.get(0),
    )?;
    log(&format!(
        "[44] Current properties_definition rows: {}",
        current_count
    ));

    // Define the correct set of properties
    let properties = vec![
        PropertyDef {
            property_id: "P17",
            property_name: "country",
            description: "sovereign state that this item is in; used to map cities and nationalities to modern countries",
            table_name: "cities, nationalities",
            column_name: "iso_country_name, iso_a3_code",
        },
        PropertyDef {
            property_id: "P19",
            property_name: "place of birth",
            description: "most specific known birth location of a person",
            table_name: "individuals, cities",
            column_name: "birthcity_en",
        },
        PropertyDef {
            property_id: "P20",
            property_name: "place of death",
            description: "most specific known death location of a person",
            table_name: "individuals, cities",
            column_name: "deathcity_en",
        },
        PropertyDef {
            property_id: "P21",
            property_name: "sex or gender",
            description: "sex or gender identity of human or animal",
            table_name: "individuals",
            column_name: "gender",
        },
        PropertyDef {
            property_id: "P27",
            property_name: "country of citizenship",
            description: "the object is a country that recognizes the subject as its citizen",
            table_name: "individuals, nationalities",
            column_name: "nationalities_en (individuals), name_en (nationalities)",
        },
        PropertyDef {
            property_id: "P30",
            property_name: "continent",
            description: "continent of which the subject is a part",
            table_name: "modern_country",
            column_name: "continent",
        },
        PropertyDef {
            property_id: "P31",
            property_name: "instance of",
            description: "type to which this subject corresponds/belongs",
            table_name: "nationalities",
            column_name: "instance_of",
        },
        PropertyDef {
            property_id: "P36",
            property_name: "capital",
            description: "seat of government of a country, province, state or other type of administrative territorial entity; used to resolve nationality-to-country mappings via capital city",
            table_name: "nationalities",
            column_name: "iso_modern_country_origin (capital_city method)",
        },
        PropertyDef {
            property_id: "P106",
            property_name: "occupation",
            description: "occupation of a person; used to select individuals (scientists, writers, artists) and populate the occupations table",
            table_name: "individuals, occupations",
            column_name: "occupations_en (individuals), name_en (occupations)",
        },
        PropertyDef {
            property_id: "P131",
            property_name: "located in the administrative territorial entity",
            description: "the item is located on the territory of the following administrative entity; used in nationality-to-country resolution chain",
            table_name: "nationalities",
            column_name: "iso_modern_country_origin (qlever_relation method)",
        },
        PropertyDef {
            property_id: "P279",
            property_name: "subclass of",
            description: "this item is a subclass of that item; used to build the occupation hierarchy (meta_occupation)",
            table_name: "occupations",
            column_name: "meta_occupation",
        },
        PropertyDef {
            property_id: "P297",
            property_name: "ISO 3166-1 alpha-2 code",
            description: "two-letter country code per ISO 3166-1; used during extraction to identify countries",
            table_name: "modern_country",
            column_name: "(used in extraction, not stored as column)",
        },
        PropertyDef {
            property_id: "P298",
            property_name: "ISO 3166-1 alpha-3 code",
            description: "three-letter country code per ISO 3166-1",
            table_name: "modern_country, nationalities, cities, individuals_countries, individuals_regions, regions",
            column_name: "iso_a3_code (or iso_a3)",
        },
        PropertyDef {
            property_id: "P569",
            property_name: "date of birth",
            description: "date on which the subject was born",
            table_name: "individuals",
            column_name: "birthdate, birthdate_precision",
        },
        PropertyDef {
            property_id: "P570",
            property_name: "date of death",
            description: "date on which the subject died",
            table_name: "individuals",
            column_name: "deathdate, deathdate_precision",
        },
        PropertyDef {
            property_id: "P625",
            property_name: "coordinate location",
            description: "geocoordinates of the subject (WGS84); used for cities and nationalities",
            table_name: "cities, nationalities",
            column_name: "lat, lon",
        },
        PropertyDef {
            property_id: "P856",
            property_name: "official website",
            description: "URL of the official page of an item; stored in identifier_types for external identifier systems",
            table_name: "identifier_types",
            column_name: "website",
        },
        PropertyDef {
            property_id: "P1366",
            property_name: "replaced by",
            description: "other entity that the subject was replaced by; used to trace historical nationalities to their modern successor countries",
            table_name: "nationalities",
            column_name: "iso_modern_country_origin (qlever_replaced_by method)",
        },
        PropertyDef {
            property_id: "P6886",
            property_name: "writing language",
            description: "language in which the writer has written their work",
            table_name: "writing_languages, individual_writing_languages, individuals",
            column_name: "name (writing_languages), language_name (individual_writing_languages), writing_language_name_en (individuals)",
        },
    ];

    // Drop and recreate
    log("[44] Dropping and recreating properties_definition table...");
    conn.execute_batch("DROP TABLE IF EXISTS properties_definition;")?;
    conn.execute_batch(
        "CREATE TABLE properties_definition (
            property_id TEXT PRIMARY KEY,
            property_name TEXT,
            description TEXT,
            table_name TEXT,
            column_name TEXT
        );",
    )?;

    // Insert all properties
    let mut stmt = conn.prepare(
        "INSERT INTO properties_definition (property_id, property_name, description, table_name, column_name)
         VALUES (?1, ?2, ?3, ?4, ?5)",
    )?;

    for p in &properties {
        stmt.execute(rusqlite::params![
            p.property_id,
            p.property_name,
            p.description,
            p.table_name,
            p.column_name,
        ])?;
    }

    let new_count: i64 = conn.query_row(
        "SELECT COUNT(*) FROM properties_definition",
        [],
        |r| r.get(0),
    )?;
    log(&format!(
        "[44] New properties_definition rows: {} (was {})",
        new_count, current_count
    ));

    // Display the final table
    log("[44] Final properties_definition:");
    let mut display = conn.prepare(
        "SELECT property_id, property_name, table_name, column_name FROM properties_definition ORDER BY property_id",
    )?;
    let rows = display.query_map([], |r| {
        Ok((
            r.get::<_, String>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, String>(2)?,
            r.get::<_, String>(3)?,
        ))
    })?;
    for r in rows {
        let (pid, pname, tname, cname) = r?;
        log(&format!("[44]   {} ({}) -> {}.{}", pid, pname, tname, cname));
    }

    log("=== Step 44 complete ===");
    Ok(())
}
