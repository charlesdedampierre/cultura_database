/// Rust insert benchmark — single transaction, prepared statement, row-by-row
/// (rusqlite has no executemany; statement reuse + WAL gives the same effect).
use anyhow::Result;
use rusqlite::{params, Connection};
use std::fs::{self, File};
use std::io::{BufRead, BufReader};
use std::time::Instant;

const TSV: &str = "benchmarks/sqlite_insert/synthetic_works.tsv";
const DB: &str = "benchmarks/sqlite_insert/rust.sqlite3";

fn fake_indiv_name(qid: &str) -> String {
    format!("Individual {}", &qid[1..])
}

fn fake_work_name(qid: &str) -> String {
    format!("Work {}", &qid[1..])
}

fn main() -> Result<()> {
    let _ = fs::remove_file(DB);
    let _ = fs::remove_file(format!("{}-wal", DB));
    let _ = fs::remove_file(format!("{}-shm", DB));

    let conn = Connection::open(DB)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL;
         PRAGMA synchronous=NORMAL;
         PRAGMA cache_size=-2000000;

         CREATE TABLE works_bench (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            individual_id   TEXT NOT NULL,
            individual_name TEXT,
            work_id         TEXT NOT NULL,
            work_name       TEXT,
            relationship    TEXT NOT NULL
         );",
    )?;

    let t0 = Instant::now();

    conn.execute_batch("BEGIN TRANSACTION;")?;
    let mut n: u64 = 0;
    {
        let mut ins = conn.prepare(
            "INSERT INTO works_bench
             (individual_id, individual_name, work_id, work_name, relationship)
             VALUES (?1, ?2, ?3, ?4, ?5)",
        )?;

        let f = File::open(TSV)?;
        let reader = BufReader::new(f);
        let mut first = true;
        for line in reader.lines() {
            let line = line?;
            if first {
                first = false;
                continue;
            }
            let parts: Vec<&str> = line.split('\t').collect();
            if parts.len() < 3 {
                continue;
            }
            let iid = parts[0];
            let wid = parts[1];
            let rel = parts[2];
            ins.execute(params![iid, fake_indiv_name(iid), wid, fake_work_name(wid), rel])?;
            n += 1;
        }
    }
    conn.execute_batch("COMMIT;")?;

    let elapsed = t0.elapsed().as_secs_f64();
    let rate = n as f64 / elapsed;
    println!(
        "RUST:   inserted {} rows in {:.2}s ({:.0} rows/s)",
        n, elapsed, rate
    );
    Ok(())
}
