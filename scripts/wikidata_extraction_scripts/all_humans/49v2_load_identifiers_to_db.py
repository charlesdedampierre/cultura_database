"""Path A — step 5 (v2, fast).

Strategy E from the 250K-row benchmark (`49bench_insert_strategies.py`):

  1. DROP the 3 secondary indexes on `identifiers`.
  2. Bare `INSERT OR IGNORE` (no JOINs) from the existing `_stage_identifiers`
     table in chunks of 600K rowids — `individual_name` / `identifier_name`
     are left NULL for new rows. The composite PK still dedupes via its
     auto-index. Each chunk is logged with throughput.
  3. CREATE the 3 secondary indexes back, individually timed.
  4. Recompute `identifier_types.count` and `individuals.identifiers_count`
     via a single GROUP BY into a temp table, then UPDATE FROM (fast).
  5. DROP `_stage_identifiers`.

The benchmark projected ~37 min for 29M rows, ~75 min for 59M staging rows.

Visibility: tqdm bar on stderr, plus per-chunk progress lines in
`logs/load_identifiers_v2.log` (tail-friendly).

This script ASSUMES `_stage_identifiers` is already populated (script 49
left it in place when it was killed). If absent, it stages from JSONs
first.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

from tqdm import tqdm


def _find_root(start: Path) -> Path:
    p = start
    for _ in range(8):
        if (p / "data" / "humans_clean.sqlite3").exists():
            return p
        p = p.parent
    return Path(__file__).resolve().parents[3]


ROOT = _find_root(Path(__file__).resolve())
DB = ROOT / "data" / "humans_clean.sqlite3"
IN_DIR = ROOT / "data" / "all_humans" / "identifiers_per_property"
PROP_LIST = ROOT / "data" / "all_humans" / "all_external_id_properties.json"
BACKUP_DIR = ROOT / "data" / "all_humans"
TASK_LOG = ROOT / "task.log"
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "load_identifiers_v2.log"
SUMMARY_FILE = LOG_DIR / "load_identifiers_v2_summary.json"

CHUNK_ROWIDS = 600_000

INDEXES = [
    ("idx_identifiers_wikidata", "wikidata_id"),
    ("idx_identifiers_property", "property_id"),
    ("idx_identifiers_name",     "individual_name"),
]


def log(msg: str) -> None:
    stamped = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(stamped, flush=True)
    LOG_DIR.mkdir(exist_ok=True)
    with TASK_LOG.open("a") as f:
        f.write(stamped + "\n")
    with LOG_FILE.open("a") as f:
        f.write(stamped + "\n")


def open_db() -> sqlite3.Connection:
    c = sqlite3.connect(DB, timeout=300, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=OFF")
    c.execute("PRAGMA temp_store=MEMORY")
    c.execute("PRAGMA cache_size=-2000000")  # 2 GB
    return c


def has_staging(conn: sqlite3.Connection) -> bool:
    r = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='_stage_identifiers'"
    ).fetchone()
    return r is not None


def stage_from_jsons(conn: sqlite3.Connection) -> int:
    """Fallback: rebuild _stage_identifiers from per-property JSONs.
    Skipped when staging table already exists (the common case here)."""
    log("[v2] _stage_identifiers missing — re-staging from JSON files")
    files = sorted(IN_DIR.glob("P*.json"), key=lambda p: int(p.stem[1:]))
    conn.execute("""
        CREATE TABLE _stage_identifiers (
            wikidata_id TEXT NOT NULL,
            property_id TEXT NOT NULL,
            value       TEXT NOT NULL
        )
    """)
    cur = conn.cursor()
    BATCH = 100_000
    buf: list[tuple[str, str, str]] = []
    n = 0
    for fp in tqdm(files, desc="stage", unit="prop"):
        try:
            d = json.loads(fp.read_text())
        except Exception:
            continue
        if d.get("error"):
            continue
        pid = d.get("pid") or fp.stem
        for qid, value in (d.get("pairs") or []):
            v = (value or "").replace("\t", " ").replace("\n", " ")
            buf.append((qid, pid, v))
            if len(buf) >= BATCH:
                cur.executemany("INSERT INTO _stage_identifiers VALUES (?,?,?)", buf)
                n += len(buf)
                buf.clear()
    if buf:
        cur.executemany("INSERT INTO _stage_identifiers VALUES (?,?,?)", buf)
        n += len(buf)
    log(f"[v2] staged {n:,} pairs")
    return n


def upsert_identifier_types(conn: sqlite3.Connection) -> int:
    """Insert any PID present in staging but missing from identifier_types."""
    canonical = json.loads(PROP_LIST.read_text())
    labels = {p["property_id"]: p.get("label") for p in canonical["properties"]}
    existing = {r[0] for r in conn.execute("SELECT property_id FROM identifier_types")}
    pids_in_data = [r[0] for r in conn.execute(
        "SELECT DISTINCT property_id FROM _stage_identifiers"
    )]
    to_add = [(p, labels.get(p) or p) for p in pids_in_data if p not in existing]
    if to_add:
        conn.execute("BEGIN")
        conn.executemany(
            "INSERT INTO identifier_types (property_id, name_en) VALUES (?, ?)",
            to_add,
        )
        conn.execute("COMMIT")
    log(f"[v2] identifier_types: +{len(to_add):,} new rows "
        f"(was {len(existing):,}, now {len(existing)+len(to_add):,})")
    return len(to_add)


def drop_secondary_indexes(conn: sqlite3.Connection) -> None:
    log("[v2] dropping 3 secondary indexes on identifiers")
    for name, _col in INDEXES:
        t0 = time.time()
        conn.execute(f"DROP INDEX IF EXISTS {name}")
        log(f"[v2]   dropped {name} ({time.time()-t0:.1f}s)")


def chunked_insert(conn: sqlite3.Connection) -> tuple[int, int]:
    n_before = conn.execute("SELECT COUNT(*) FROM identifiers").fetchone()[0]
    max_rowid = conn.execute("SELECT MAX(rowid) FROM _stage_identifiers").fetchone()[0]
    log(f"[v2] identifiers before insert: {n_before:,}")
    log(f"[v2] _stage_identifiers max rowid: {max_rowid:,}")

    n_chunks = (max_rowid + CHUNK_ROWIDS - 1) // CHUNK_ROWIDS
    log(f"[v2] running INSERT OR IGNORE in {n_chunks:,} chunks of {CHUNK_ROWIDS:,} rowids")

    cur = conn.cursor()
    t_start = time.time()

    pbar = tqdm(total=max_rowid, unit="row", desc="insert", smoothing=0.1)
    for chunk_idx, start in enumerate(range(0, max_rowid, CHUNK_ROWIDS), start=1):
        end = start + CHUNK_ROWIDS
        t0 = time.time()
        cur.execute("""
            INSERT OR IGNORE INTO identifiers (wikidata_id, property_id, value)
            SELECT wikidata_id, property_id, value
            FROM _stage_identifiers
            WHERE rowid > ? AND rowid <= ?
        """, (start, end))
        chunk_rows = min(CHUNK_ROWIDS, max_rowid - start)
        pbar.update(chunk_rows)
        elapsed = time.time() - t0
        rate = chunk_rows / max(elapsed, 0.01)
        # Per-chunk log line — tail-friendly, no \r escapes
        if chunk_idx % 5 == 0 or chunk_idx == n_chunks:
            total_elapsed = time.time() - t_start
            done = chunk_idx * CHUNK_ROWIDS
            eta_s = (max_rowid - done) / max(done / total_elapsed, 0.01)
            log(f"[v2] chunk {chunk_idx}/{n_chunks}  "
                f"rate={rate:,.0f} rows/s  "
                f"elapsed={total_elapsed/60:.1f}min  eta={eta_s/60:.1f}min")
    pbar.close()

    n_after = conn.execute("SELECT COUNT(*) FROM identifiers").fetchone()[0]
    n_inserted = n_after - n_before
    log(f"[v2] insert done: {n_inserted:,} new rows  "
        f"(table: {n_before:,} → {n_after:,})  "
        f"in {(time.time()-t_start)/60:.1f}min")
    return n_inserted, n_after


def recreate_indexes(conn: sqlite3.Connection) -> None:
    for name, col in INDEXES:
        log(f"[v2] CREATE INDEX {name} ON identifiers({col}) — building…")
        t0 = time.time()
        conn.execute(f"CREATE INDEX {name} ON identifiers({col})")
        log(f"[v2]   {name} built in {time.time()-t0:.1f}s")


def recompute_counts_fast(conn: sqlite3.Connection) -> None:
    log("[v2] recomputing identifier_types.count via GROUP BY → temp table")
    t0 = time.time()
    conn.execute("DROP TABLE IF EXISTS _pid_counts")
    conn.execute("""
        CREATE TEMP TABLE _pid_counts AS
        SELECT property_id, COUNT(*) AS c
        FROM identifiers
        GROUP BY property_id
    """)
    conn.execute("CREATE INDEX _idx_pid_counts ON _pid_counts(property_id)")
    conn.execute("""
        UPDATE identifier_types
           SET count = COALESCE(
               (SELECT c FROM _pid_counts WHERE _pid_counts.property_id = identifier_types.property_id),
               0)
    """)
    log(f"[v2]   identifier_types.count updated in {(time.time()-t0)/60:.1f}min")

    log("[v2] recomputing individuals.identifiers_count via GROUP BY → temp table")
    t0 = time.time()
    conn.execute("DROP TABLE IF EXISTS _qid_counts")
    conn.execute("""
        CREATE TEMP TABLE _qid_counts AS
        SELECT wikidata_id, COUNT(*) AS c
        FROM identifiers
        GROUP BY wikidata_id
    """)
    conn.execute("CREATE INDEX _idx_qid_counts ON _qid_counts(wikidata_id)")
    conn.execute("""
        UPDATE individuals
           SET identifiers_count = COALESCE(
               (SELECT c FROM _qid_counts WHERE _qid_counts.wikidata_id = individuals.wikidata_id),
               0)
    """)
    log(f"[v2]   individuals.identifiers_count updated in {(time.time()-t0)/60:.1f}min")


def main() -> None:
    if not DB.exists():
        log(f"[v2] DB not found: {DB}")
        sys.exit(1)

    log(f"[v2] strategy E start  (DB={DB.name})")
    t_overall = time.time()

    conn = open_db()

    if not has_staging(conn):
        stage_from_jsons(conn)
    else:
        n = conn.execute("SELECT COUNT(*) FROM _stage_identifiers").fetchone()[0]
        log(f"[v2] reusing existing _stage_identifiers ({n:,} rows)")

    upsert_identifier_types(conn)
    drop_secondary_indexes(conn)
    n_inserted, n_total_after = chunked_insert(conn)
    recreate_indexes(conn)
    recompute_counts_fast(conn)

    log("[v2] dropping _stage_identifiers")
    conn.execute("DROP TABLE _stage_identifiers")

    final_types = conn.execute("SELECT COUNT(*) FROM identifier_types").fetchone()[0]
    final_idents = conn.execute("SELECT COUNT(*) FROM identifiers").fetchone()[0]
    new_with_null_names = conn.execute("""
        SELECT COUNT(*) FROM identifiers WHERE individual_name IS NULL
    """).fetchone()[0]

    summary = {
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "strategy": "E (drop indexes / bare INSERT / recreate)",
        "elapsed_minutes": round((time.time() - t_overall) / 60, 2),
        "n_identifiers_inserted": n_inserted,
        "final_identifier_types_count": final_types,
        "final_identifiers_count": final_idents,
        "rows_with_null_individual_name": new_with_null_names,
    }
    SUMMARY_FILE.write_text(json.dumps(summary, indent=2))
    log(f"[v2] DONE in {(time.time()-t_overall)/60:.1f}min — summary: {SUMMARY_FILE.name}")
    log(json.dumps(summary, indent=2))
    conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"[v2] FATAL: {e}")
        raise
