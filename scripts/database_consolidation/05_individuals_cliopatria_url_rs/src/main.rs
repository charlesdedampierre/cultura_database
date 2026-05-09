// URL + floruit-year matcher for Cliopatria polities (Rust + DuckDB).
//
// Per individual, cascade:
//   1) country_of_citizenship URL
//   2) deathplace URL
//   3) birthplace URL
// joined to `polities_cliopatria.wikipedia_url` and restricted to polity-periods
// whose [from_year, to_year] contains the impact year. Impact year is the
// midpoint of (floruit_period_start, floruit_period_end) when both are present,
// else `floruit_year`.
//
// Output: table `individuals_cliopatria_url` in `data/humans_clean.duckdb`,
// inserted via the DuckDB Appender API. The existing `individuals_cliopatria`
// table (polygon-based) is left untouched.

use anyhow::{Context, Result};
use clap::Parser;
use duckdb::{params, Connection};
use rayon::prelude::*;
use std::collections::HashMap;
use std::path::PathBuf;
use std::time::Instant;

#[derive(Parser, Debug)]
struct Args {
    #[arg(long, default_value = "data/humans_clean.duckdb")]
    db: PathBuf,
    #[arg(long, default_value = "individuals_cliopatria_url")]
    table: String,
}

#[derive(Clone)]
struct UrlPeriod {
    polity_id: i64,
    polity_name: String,
    from_year: i32,
    to_year: i32,
}

fn split_ids(s: &str) -> Vec<&str> {
    s.split(';')
        .map(|x| x.trim())
        .filter(|x| !x.is_empty())
        .collect()
}

fn main() -> Result<()> {
    let args = Args::parse();
    let t_total = Instant::now();
    println!("db: {}", args.db.display());
    println!("target table: {}", args.table);
    println!();

    let conn = Connection::open(&args.db)
        .with_context(|| format!("opening duckdb at {}", args.db.display()))?;
    conn.execute_batch("PRAGMA threads=0;").ok();

    // ---------------------------------------------------------------
    // 1. Polities + period years -> url -> Vec<UrlPeriod>
    // ---------------------------------------------------------------
    let mut t = Instant::now();

    let mut polity_url: HashMap<i64, String> = HashMap::new();
    let mut polity_name: HashMap<i64, String> = HashMap::new();
    {
        let mut stmt = conn.prepare("SELECT id, name, wikipedia_url FROM polities_cliopatria")?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, Option<String>>(1)?.unwrap_or_default(),
                r.get::<_, Option<String>>(2)?.unwrap_or_default(),
            ))
        })?;
        for row in rows {
            let (id, name, url) = row?;
            polity_name.insert(id, name);
            if !url.is_empty() {
                polity_url.insert(id, url);
            }
        }
    }

    let mut polity_periods: HashMap<i64, Vec<(i32, i32)>> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT polity_id, from_year, to_year FROM polities_periods_cliopatria",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, Option<i64>>(1)?,
                r.get::<_, Option<i64>>(2)?,
            ))
        })?;
        for row in rows {
            let (pid, fy, ty) = row?;
            if let (Some(f), Some(t)) = (fy, ty) {
                polity_periods
                    .entry(pid)
                    .or_default()
                    .push((f as i32, t as i32));
            }
        }
    }

    let mut url_index: HashMap<String, Vec<UrlPeriod>> = HashMap::new();
    for (pid, url) in &polity_url {
        let Some(years) = polity_periods.get(pid) else {
            continue;
        };
        let name = polity_name.get(pid).cloned().unwrap_or_default();
        let bucket = url_index.entry(url.clone()).or_default();
        for (fy, ty) in years {
            bucket.push(UrlPeriod {
                polity_id: *pid,
                polity_name: name.clone(),
                from_year: *fy,
                to_year: *ty,
            });
        }
    }
    let n_url_entries: usize = url_index.values().map(|v| v.len()).sum();
    println!(
        "  polities={} url_index_keys={} url_index_rows={} [{:.2}s]",
        polity_name.len(),
        url_index.len(),
        n_url_entries,
        t.elapsed().as_secs_f64()
    );

    // ---------------------------------------------------------------
    // 2. URL maps for places + country_of_citizenship
    // ---------------------------------------------------------------
    t = Instant::now();
    let mut place_url: HashMap<String, (String, String)> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT id, name_en, en_wikipedia_url_original_country_name FROM places \
             WHERE en_wikipedia_url_original_country_name IS NOT NULL \
                   AND en_wikipedia_url_original_country_name <> ''",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, Option<String>>(0)?.unwrap_or_default(),
                r.get::<_, Option<String>>(1)?.unwrap_or_default(),
                r.get::<_, Option<String>>(2)?.unwrap_or_default(),
            ))
        })?;
        for row in rows {
            let (id, name, url) = row?;
            if !id.is_empty() && !url.is_empty() {
                place_url.entry(id).or_insert((name, url));
            }
        }
    }
    let mut coc_url: HashMap<String, (String, String)> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT wikidata_id, name_en, en_wikipedia_url FROM country_of_citizenship \
             WHERE en_wikipedia_url IS NOT NULL AND en_wikipedia_url <> ''",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, Option<String>>(0)?.unwrap_or_default(),
                r.get::<_, Option<String>>(1)?.unwrap_or_default(),
                r.get::<_, Option<String>>(2)?.unwrap_or_default(),
            ))
        })?;
        for row in rows {
            let (id, name, url) = row?;
            if !id.is_empty() && !url.is_empty() {
                coc_url.entry(id).or_insert((name, url));
            }
        }
    }
    println!(
        "  place_url={} coc_url={} [{:.2}s]",
        place_url.len(),
        coc_url.len(),
        t.elapsed().as_secs_f64()
    );

    // ---------------------------------------------------------------
    // 3. Individuals + keys + floruit period
    // ---------------------------------------------------------------
    t = Instant::now();

    struct Individual {
        wikidata_id: String,
        name_en: String,
        birthcity_id: String,
        deathcity_id: String,
        coc_ids: String,
        floruit_period_start: Option<i64>,
        floruit_period_end: Option<i64>,
        year: Option<i32>,
    }

    let mut individuals: Vec<Individual> = Vec::new();
    {
        let mut stmt = conn.prepare(
            "SELECT i.wikidata_id, i.name_en, \
                    k.birthcity_id, k.deathcity_id, k.country_of_citizenship_ids, \
                    f.floruit_period_start, f.floruit_period_end, f.floruit_year \
             FROM individuals i \
             LEFT JOIN individuals_keys k ON i.wikidata_id = k.wikidata_id \
             LEFT JOIN individuals_floruit_period f ON i.wikidata_id = f.wikidata_id",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, Option<String>>(0)?.unwrap_or_default(),
                r.get::<_, Option<String>>(1)?.unwrap_or_default(),
                r.get::<_, Option<String>>(2)?.unwrap_or_default(),
                r.get::<_, Option<String>>(3)?.unwrap_or_default(),
                r.get::<_, Option<String>>(4)?.unwrap_or_default(),
                r.get::<_, Option<i64>>(5)?,
                r.get::<_, Option<i64>>(6)?,
                r.get::<_, Option<i64>>(7)?,
            ))
        })?;
        for row in rows {
            let (wid, name, b, d, c, fps, fpe, fy) = row?;
            if wid.is_empty() {
                continue;
            }
            let year = if let (Some(s), Some(e)) = (fps, fpe) {
                Some(((s + e) / 2) as i32)
            } else {
                fy.map(|v| v as i32)
            };
            individuals.push(Individual {
                wikidata_id: wid,
                name_en: name,
                birthcity_id: b,
                deathcity_id: d,
                coc_ids: c,
                floruit_period_start: fps,
                floruit_period_end: fpe,
                year,
            });
        }
    }
    let n_with_year = individuals.iter().filter(|i| i.year.is_some()).count();
    println!(
        "  individuals={} with_year={} [{:.2}s]",
        individuals.len(),
        n_with_year,
        t.elapsed().as_secs_f64()
    );

    // ---------------------------------------------------------------
    // 4. Cascade match (coc URL -> death URL -> birth URL)
    // ---------------------------------------------------------------
    t = Instant::now();

    struct Match {
        wikidata_id: String,
        name_en: String,
        polity_id: i64,
        polity_name: String,
        origin: &'static str,
        matched_name: String,
        matched_wikidata_id: String,
        floruit_year: i32,
        floruit_period_start: Option<i64>,
        floruit_period_end: Option<i64>,
    }

    let url_match = |url: &str, year: i32| -> Option<&UrlPeriod> {
        let bucket = url_index.get(url)?;
        bucket
            .iter()
            .find(|e| year >= e.from_year && year <= e.to_year)
    };

    let matches: Vec<Match> = individuals
        .par_iter()
        .filter_map(|ind| {
            let year = ind.year?;

            // 1) coc URL — first coc_id with year-matching url
            for cid in split_ids(&ind.coc_ids) {
                if let Some((cname, curl)) = coc_url.get(cid) {
                    if let Some(up) = url_match(curl, year) {
                        return Some(Match {
                            wikidata_id: ind.wikidata_id.clone(),
                            name_en: ind.name_en.clone(),
                            polity_id: up.polity_id,
                            polity_name: up.polity_name.clone(),
                            origin: "country_of_citizenship",
                            matched_name: cname.clone(),
                            matched_wikidata_id: cid.to_string(),
                            floruit_year: year,
                            floruit_period_start: ind.floruit_period_start,
                            floruit_period_end: ind.floruit_period_end,
                        });
                    }
                }
            }

            // 2) deathplace URL
            let did = ind.deathcity_id.trim();
            if !did.is_empty() {
                if let Some((pn, purl)) = place_url.get(did) {
                    if let Some(up) = url_match(purl, year) {
                        return Some(Match {
                            wikidata_id: ind.wikidata_id.clone(),
                            name_en: ind.name_en.clone(),
                            polity_id: up.polity_id,
                            polity_name: up.polity_name.clone(),
                            origin: "deathplace",
                            matched_name: pn.clone(),
                            matched_wikidata_id: did.to_string(),
                            floruit_year: year,
                            floruit_period_start: ind.floruit_period_start,
                            floruit_period_end: ind.floruit_period_end,
                        });
                    }
                }
            }

            // 3) birthplace URL
            let bid = ind.birthcity_id.trim();
            if !bid.is_empty() {
                if let Some((pn, purl)) = place_url.get(bid) {
                    if let Some(up) = url_match(purl, year) {
                        return Some(Match {
                            wikidata_id: ind.wikidata_id.clone(),
                            name_en: ind.name_en.clone(),
                            polity_id: up.polity_id,
                            polity_name: up.polity_name.clone(),
                            origin: "birthplace",
                            matched_name: pn.clone(),
                            matched_wikidata_id: bid.to_string(),
                            floruit_year: year,
                            floruit_period_start: ind.floruit_period_start,
                            floruit_period_end: ind.floruit_period_end,
                        });
                    }
                }
            }

            None
        })
        .collect();

    let cascade_t = t.elapsed();
    println!(
        "  matched={} [{:.2}s]",
        matches.len(),
        cascade_t.as_secs_f64()
    );

    // ---------------------------------------------------------------
    // 5. Write to DuckDB via Appender
    // ---------------------------------------------------------------
    t = Instant::now();
    conn.execute_batch(&format!("DROP TABLE IF EXISTS {};", args.table))?;
    conn.execute_batch(&format!(
        "CREATE TABLE {} (\
            wikidata_id VARCHAR PRIMARY KEY,\
            name_en VARCHAR,\
            polity_id BIGINT,\
            polity_name VARCHAR,\
            origin VARCHAR,\
            matched_name VARCHAR,\
            matched_wikidata_id VARCHAR,\
            method VARCHAR,\
            floruit_year INTEGER,\
            floruit_period_start INTEGER,\
            floruit_period_end INTEGER\
        );",
        args.table
    ))?;

    {
        let mut appender = conn.appender(&args.table)?;
        for m in &matches {
            appender.append_row(params![
                &m.wikidata_id,
                &m.name_en,
                m.polity_id,
                &m.polity_name,
                m.origin,
                &m.matched_name,
                &m.matched_wikidata_id,
                "merge_with_url",
                m.floruit_year,
                m.floruit_period_start,
                m.floruit_period_end,
            ])?;
        }
        appender.flush()?;
    }

    conn.execute_batch(&format!(
        "CREATE INDEX IF NOT EXISTS idx_{0}_polity_id ON {0}(polity_id);",
        args.table
    ))?;
    let write_t = t.elapsed();
    println!(
        "  inserted into {} [{:.2}s]",
        args.table,
        write_t.as_secs_f64()
    );

    // breakdown
    let mut buckets: HashMap<&str, usize> = HashMap::new();
    for m in &matches {
        *buckets.entry(m.origin).or_default() += 1;
    }
    let mut bd: Vec<_> = buckets.into_iter().collect();
    bd.sort_by(|a, b| b.1.cmp(&a.1));
    println!();
    for (origin, n) in &bd {
        println!("    {:25} n={:>10}", origin, n);
    }
    println!(
        "\nDONE matched={} -> {}::{} in {:.2}s",
        matches.len(),
        args.db.display(),
        args.table,
        t_total.elapsed().as_secs_f64()
    );

    Ok(())
}
