// 06 — Tag fictional connections in `individuals_cliopatria`.
//
// We exclude individuals whose country_of_citizenship, birthplace, or deathplace
// is a fictional polity (e.g. fictional country Q1378024, fictional state Q1145276).
// A `non_human` flag is added to `individuals_cliopatria` and set to 1 for
// individuals connected to any fictional CoC or fictional place.
//
// Detection (in DuckDB):
//   - fictional CoC = country_of_citizenship rows whose `instance_labels`
//     contains fiction / myth / legend / imaginary / hypothetical.
//   - fictional place = places rows whose `entity_type` matches the same
//     vocabulary.

use anyhow::{Context, Result};
use clap::Parser;
use duckdb::Connection;
use std::path::PathBuf;
use std::time::Instant;

#[derive(Parser, Debug)]
struct Args {
    #[arg(long, default_value = "data/humans_clean.duckdb")]
    db: PathBuf,
    #[arg(long, default_value = "individuals_cliopatria")]
    table: String,
}

const FICTIONAL_FILTER: &str = "(\
    instance_labels ILIKE '%fiction%' \
 OR instance_labels ILIKE '%myth%' \
 OR instance_labels ILIKE '%legend%' \
 OR instance_labels ILIKE '%imaginary%' \
 OR instance_labels ILIKE '%hypothetical%')";

const FICTIONAL_PLACE_FILTER: &str = "(\
    entity_type ILIKE '%fiction%' \
 OR entity_type ILIKE '%myth%' \
 OR entity_type ILIKE '%legend%' \
 OR entity_type ILIKE '%imaginary%' \
 OR entity_type ILIKE '%hypothetical%')";

fn main() -> Result<()> {
    let args = Args::parse();
    let t_total = Instant::now();
    println!("db: {}", args.db.display());
    println!("target table: {}", args.table);
    println!();

    let conn = Connection::open(&args.db)
        .with_context(|| format!("opening duckdb at {}", args.db.display()))?;
    conn.execute_batch("PRAGMA threads=0;")?;

    // ------------------------------------------------------------------
    // 1. Fictional CoC + place id sets
    // ------------------------------------------------------------------
    let mut t = Instant::now();
    conn.execute_batch(&format!(
        "DROP TABLE IF EXISTS _fictional_coc;\
         CREATE TEMP TABLE _fictional_coc AS \
         SELECT wikidata_id AS id, name_en, instance_labels \
         FROM country_of_citizenship \
         WHERE {FILTER};",
        FILTER = FICTIONAL_FILTER
    ))?;
    let n_fict_coc: i64 = conn
        .query_row("SELECT COUNT(*) FROM _fictional_coc", [], |r| r.get(0))?;

    conn.execute_batch(&format!(
        "DROP TABLE IF EXISTS _fictional_place;\
         CREATE TEMP TABLE _fictional_place AS \
         SELECT id, name_en, entity_type \
         FROM places \
         WHERE {FILTER};",
        FILTER = FICTIONAL_PLACE_FILTER
    ))?;
    let n_fict_place: i64 = conn
        .query_row("SELECT COUNT(*) FROM _fictional_place", [], |r| r.get(0))?;

    println!(
        "  fictional CoC entities  = {} [{:.2}s]",
        n_fict_coc,
        t.elapsed().as_secs_f64()
    );
    println!("  fictional place entries = {}", n_fict_place);

    // ------------------------------------------------------------------
    // 2. Per-individual sets
    //    - indiv_fict_coc   : individuals with at least one fictional CoC
    //    - indiv_fict_birth : individuals whose birthcity is fictional
    //    - indiv_fict_death : individuals whose deathcity is fictional
    // ------------------------------------------------------------------
    t = Instant::now();
    conn.execute_batch(
        "DROP TABLE IF EXISTS _indiv_fict_coc;\
         CREATE TEMP TABLE _indiv_fict_coc AS \
         WITH coc_long AS ( \
            SELECT k.wikidata_id, TRIM(t.cid) AS coc_id \
            FROM individuals_keys k, \
                 UNNEST(string_split(k.country_of_citizenship_ids, ';')) AS t(cid) \
            WHERE k.country_of_citizenship_ids IS NOT NULL \
              AND TRIM(t.cid) <> '' \
         ) \
         SELECT DISTINCT cl.wikidata_id \
         FROM coc_long cl \
         JOIN _fictional_coc fc ON fc.id = cl.coc_id;",
    )?;
    let n_indiv_fict_coc: i64 =
        conn.query_row("SELECT COUNT(*) FROM _indiv_fict_coc", [], |r| r.get(0))?;

    conn.execute_batch(
        "DROP TABLE IF EXISTS _indiv_fict_birth;\
         CREATE TEMP TABLE _indiv_fict_birth AS \
         SELECT DISTINCT k.wikidata_id \
         FROM individuals_keys k \
         JOIN _fictional_place fp ON fp.id = k.birthcity_id;",
    )?;
    let n_indiv_fict_birth: i64 =
        conn.query_row("SELECT COUNT(*) FROM _indiv_fict_birth", [], |r| r.get(0))?;

    conn.execute_batch(
        "DROP TABLE IF EXISTS _indiv_fict_death;\
         CREATE TEMP TABLE _indiv_fict_death AS \
         SELECT DISTINCT k.wikidata_id \
         FROM individuals_keys k \
         JOIN _fictional_place fp ON fp.id = k.deathcity_id;",
    )?;
    let n_indiv_fict_death: i64 =
        conn.query_row("SELECT COUNT(*) FROM _indiv_fict_death", [], |r| r.get(0))?;

    conn.execute_batch(
        "DROP TABLE IF EXISTS _indiv_fict_any;\
         CREATE TEMP TABLE _indiv_fict_any AS \
         SELECT wikidata_id FROM _indiv_fict_coc \
         UNION \
         SELECT wikidata_id FROM _indiv_fict_birth \
         UNION \
         SELECT wikidata_id FROM _indiv_fict_death;",
    )?;
    let n_indiv_fict_any: i64 =
        conn.query_row("SELECT COUNT(*) FROM _indiv_fict_any", [], |r| r.get(0))?;

    println!(
        "  individuals with fictional CoC        = {} (across whole DB)",
        n_indiv_fict_coc
    );
    println!(
        "  individuals with fictional birthplace = {}",
        n_indiv_fict_birth
    );
    println!(
        "  individuals with fictional deathplace = {}",
        n_indiv_fict_death
    );
    println!(
        "  individuals with ANY fictional link   = {} [{:.2}s]",
        n_indiv_fict_any,
        t.elapsed().as_secs_f64()
    );

    // ------------------------------------------------------------------
    // 3. Add non_human column to individuals_cliopatria + flag rows
    // ------------------------------------------------------------------
    t = Instant::now();
    let cols: Vec<String> = {
        let mut stmt = conn.prepare(&format!("PRAGMA table_info('{}')", args.table))?;
        let mut out = Vec::new();
        let rows = stmt.query_map([], |r| r.get::<_, String>(1))?;
        for r in rows {
            out.push(r?);
        }
        out
    };
    if !cols.iter().any(|c| c == "non_human") {
        conn.execute_batch(&format!(
            "ALTER TABLE {} ADD COLUMN non_human INTEGER NOT NULL DEFAULT 0;",
            args.table
        ))?;
        println!("  added column {}.non_human", args.table);
    } else {
        conn.execute_batch(&format!("UPDATE {} SET non_human = 0;", args.table))?;
        println!("  reset {}.non_human", args.table);
    }

    // Apply the flag in the linked table.
    conn.execute_batch(&format!(
        "UPDATE {0} SET non_human = 1 \
         WHERE wikidata_id IN (SELECT wikidata_id FROM _indiv_fict_any);",
        args.table
    ))?;
    let n_flagged_in_table: i64 = conn.query_row(
        &format!("SELECT COUNT(*) FROM {} WHERE non_human = 1", args.table),
        [],
        |r| r.get(0),
    )?;
    let n_flagged_coc_in_table: i64 = conn.query_row(
        &format!(
            "SELECT COUNT(*) FROM {} \
             WHERE wikidata_id IN (SELECT wikidata_id FROM _indiv_fict_coc)",
            args.table
        ),
        [],
        |r| r.get(0),
    )?;
    conn.execute_batch(&format!(
        "CREATE INDEX IF NOT EXISTS idx_{0}_non_human ON {0}(non_human);",
        args.table
    ))?;
    println!(
        "  rows flagged non_human=1 in {}      = {} [{:.2}s]",
        args.table,
        n_flagged_in_table,
        t.elapsed().as_secs_f64()
    );

    // ------------------------------------------------------------------
    // 4. Paper-friendly summary
    // ------------------------------------------------------------------
    let total_in_table: i64 = conn.query_row(
        &format!("SELECT COUNT(*) FROM {}", args.table),
        [],
        |r| r.get(0),
    )?;
    println!();
    println!("============== summary for paper ==============");
    println!(
        "  fictional CoC polities identified         : {}",
        n_fict_coc
    );
    println!(
        "  fictional place entries identified        : {}",
        n_fict_place
    );
    println!(
        "  individuals (whole DB) with fictional CoC : {}",
        n_indiv_fict_coc
    );
    println!(
        "  individuals in {} with fictional CoC : {}  <- X (CoC-only filter)",
        args.table, n_flagged_coc_in_table
    );
    println!(
        "  individuals in {} flagged non_human  : {}  ({}/{} = {:.2}%)",
        args.table,
        n_flagged_in_table,
        n_flagged_in_table,
        total_in_table,
        (n_flagged_in_table as f64 / total_in_table as f64) * 100.0
    );
    println!();
    println!(
        "DONE in {:.2}s -> {}::{}",
        t_total.elapsed().as_secs_f64(),
        args.db.display(),
        args.table
    );
    Ok(())
}
