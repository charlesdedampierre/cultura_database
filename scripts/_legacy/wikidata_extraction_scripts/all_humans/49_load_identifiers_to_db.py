"""Path A — step 5.

Load every per-property identifier extract (`data/all_humans/identifiers_per_property/<Pxxx>.json`)
into the local SQLite (`data/humans_clean.sqlite3`) — both the
`identifier_types` metadata table and the row-level `identifiers` table.

Behaviour
---------
- `identifier_types`: insert rows for any PID not yet present, using the
  canonical Wikidata label from `all_external_id_properties.json`. Existing
  rows (with their richer metadata) are LEFT UNTOUCHED.
- `identifiers`: every (wikidata_id, property_id, value) triple is appended
  with `INSERT OR IGNORE` (the table's primary key dedupes against any rows
  already in the DB). `individual_name` and `identifier_name` are populated
  by JOIN from `individuals` and `identifier_types`. `url` is left NULL
  (matches existing convention).
- Final pass recomputes `identifier_types.count` and
  `individuals.identifiers_count` from the actual `identifiers` content.

Safety: the existing `identifier_types` content is dumped to
`data/all_humans/identifier_types_backup_<ts>.json` before any write.
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
LOG_FILE = LOG_DIR / "load_identifiers_to_db.log"
SUMMARY_FILE = LOG_DIR / "load_identifiers_to_db_summary.json"

BATCH = 100_000


def log(msg: str) -> None:
    stamped = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(stamped, flush=True)
    LOG_DIR.mkdir(exist_ok=True)
    with TASK_LOG.open("a") as f:
        f.write(stamped + "\n")
    with LOG_FILE.open("a") as f:
        f.write(stamped + "\n")


def backup_identifier_types(conn: sqlite3.Connection) -> Path:
    rows = conn.execute("SELECT * FROM identifier_types").fetchall()
    cols = [c[1] for c in conn.execute("PRAGMA table_info(identifier_types)")]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = BACKUP_DIR / f"identifier_types_backup_{ts}.json"
    out.write_text(json.dumps({
        "backed_up_at": datetime.now().isoformat(timespec="seconds"),
        "columns": cols,
        "rows": [list(r) for r in rows],
    }, ensure_ascii=False))
    log(f"[49] backed up {len(rows):,} identifier_types rows -> {out.name}")
    return out


def load_canonical_labels() -> dict[str, str]:
    data = json.loads(PROP_LIST.read_text())
    return {p["property_id"]: p.get("label") for p in data["properties"]}


def stage_pairs(conn: sqlite3.Connection) -> tuple[int, int, list[str]]:
    """Stream every (wikidata_id, property_id, value) from the per-property
    JSONs into a temp staging table. Returns (n_files_ok, n_pairs_total,
    pids_with_data)."""
    conn.execute("DROP TABLE IF EXISTS _stage_identifiers")
    conn.execute("""
        CREATE TABLE _stage_identifiers (
            wikidata_id TEXT NOT NULL,
            property_id TEXT NOT NULL,
            value       TEXT NOT NULL
        )
    """)

    files = sorted(IN_DIR.glob("P*.json"), key=lambda p: int(p.stem[1:]))
    log(f"[49] streaming {len(files):,} per-property JSONs into _stage_identifiers")

    pids_with_data: list[str] = []
    n_files_ok = 0
    n_pairs_total = 0
    buf: list[tuple[str, str, str]] = []

    cur = conn.cursor()
    for fp in tqdm(files, desc="stage", unit="prop"):
        try:
            d = json.loads(fp.read_text())
        except Exception:
            continue
        if d.get("error"):
            continue
        pid = d.get("pid") or fp.stem
        n_files_ok += 1
        pairs = d.get("pairs") or []
        if not pairs:
            continue
        pids_with_data.append(pid)
        for qid, value in pairs:
            v = (value or "").replace("\t", " ").replace("\n", " ")
            buf.append((qid, pid, v))
            if len(buf) >= BATCH:
                cur.executemany(
                    "INSERT INTO _stage_identifiers VALUES (?,?,?)", buf
                )
                n_pairs_total += len(buf)
                buf.clear()
    if buf:
        cur.executemany(
            "INSERT INTO _stage_identifiers VALUES (?,?,?)", buf
        )
        n_pairs_total += len(buf)
        buf.clear()
    conn.commit()
    log(f"[49] staged {n_pairs_total:,} pairs from {n_files_ok:,} files "
        f"({len(pids_with_data):,} PIDs with at least one pair)")

    log("[49] indexing staging table…")
    conn.execute("CREATE INDEX idx_stage_qid ON _stage_identifiers(wikidata_id)")
    conn.execute("CREATE INDEX idx_stage_pid ON _stage_identifiers(property_id)")
    conn.commit()

    return n_files_ok, n_pairs_total, pids_with_data


def upsert_identifier_types(conn: sqlite3.Connection,
                            pids_with_data: list[str],
                            labels: dict[str, str]) -> int:
    """Insert any PID present in the data but missing from identifier_types
    (uses canonical Wikidata label)."""
    existing = {r[0] for r in conn.execute("SELECT property_id FROM identifier_types")}
    to_add = [(p, labels.get(p) or p) for p in pids_with_data if p not in existing]
    if to_add:
        conn.executemany(
            "INSERT INTO identifier_types (property_id, name_en) VALUES (?, ?)",
            to_add,
        )
        conn.commit()
    log(f"[49] inserted {len(to_add):,} new rows into identifier_types "
        f"(table now has {len(existing) + len(to_add):,} rows)")
    return len(to_add)


def insert_identifiers(conn: sqlite3.Connection) -> int:
    """Bulk-insert from staging into the canonical identifiers table.
    INSERT OR IGNORE on PK (wikidata_id, property_id, value) keeps existing
    rows untouched."""
    n_before = conn.execute("SELECT COUNT(*) FROM identifiers").fetchone()[0]
    log(f"[49] identifiers row count before insert: {n_before:,}")
    log("[49] running JOIN-based INSERT OR IGNORE into identifiers (no progress meter — single SQL statement)")
    t0 = time.time()
    conn.execute("""
        INSERT OR IGNORE INTO identifiers
            (wikidata_id, individual_name, property_id, identifier_name, value, url)
        SELECT
            s.wikidata_id,
            i.name_en,
            s.property_id,
            t.name_en,
            s.value,
            NULL
        FROM _stage_identifiers s
        LEFT JOIN individuals      i ON i.wikidata_id = s.wikidata_id
        LEFT JOIN identifier_types t ON t.property_id = s.property_id
    """)
    conn.commit()
    n_after = conn.execute("SELECT COUNT(*) FROM identifiers").fetchone()[0]
    log(f"[49] identifiers row count after insert: {n_after:,} "
        f"(+{n_after - n_before:,} new) — elapsed {(time.time()-t0)/60:.1f} min")
    return n_after - n_before


def recompute_counts(conn: sqlite3.Connection) -> None:
    log("[49] recomputing identifier_types.count from actual identifiers")
    conn.execute("""
        UPDATE identifier_types
           SET count = COALESCE((
                SELECT COUNT(*) FROM identifiers
                 WHERE identifiers.property_id = identifier_types.property_id
           ), 0)
    """)
    conn.commit()
    log("[49] recomputing individuals.identifiers_count from actual identifiers")
    conn.execute("""
        UPDATE individuals
           SET identifiers_count = COALESCE((
                SELECT COUNT(*) FROM identifiers
                 WHERE identifiers.wikidata_id = individuals.wikidata_id
           ), 0)
    """)
    conn.commit()


def main() -> None:
    if not DB.exists():
        log(f"[49] DB not found: {DB}")
        sys.exit(1)
    if not IN_DIR.exists():
        log(f"[49] per-property JSONs not found at {IN_DIR}")
        sys.exit(1)

    log(f"[49] starting integration into {DB}")
    t0 = time.time()

    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-2000000")  # 2 GB page cache

    backup_path = backup_identifier_types(conn)
    labels = load_canonical_labels()

    n_files_ok, n_staged, pids_with_data = stage_pairs(conn)
    n_new_types = upsert_identifier_types(conn, pids_with_data, labels)
    n_inserted = insert_identifiers(conn)
    recompute_counts(conn)

    log("[49] dropping staging table")
    conn.execute("DROP TABLE _stage_identifiers")
    conn.commit()

    log("[49] running ANALYZE on touched tables (light)")
    conn.execute("ANALYZE identifier_types")
    conn.execute("ANALYZE identifiers")
    conn.commit()

    final_types = conn.execute("SELECT COUNT(*) FROM identifier_types").fetchone()[0]
    final_idents = conn.execute("SELECT COUNT(*) FROM identifiers").fetchone()[0]
    types_with_zero = conn.execute(
        "SELECT COUNT(*) FROM identifier_types WHERE count = 0"
    ).fetchone()[0]

    summary = {
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "elapsed_minutes": round((time.time() - t0) / 60, 2),
        "backup_path": str(backup_path.relative_to(ROOT)),
        "n_files_streamed_ok": n_files_ok,
        "n_pairs_staged": n_staged,
        "n_new_identifier_types_added": n_new_types,
        "n_identifier_rows_inserted": n_inserted,
        "final_identifier_types_count": final_types,
        "final_identifiers_count": final_idents,
        "identifier_types_with_zero_humans": types_with_zero,
    }
    SUMMARY_FILE.write_text(json.dumps(summary, indent=2))
    log(f"[49] DONE in {(time.time() - t0)/60:.1f} min — summary: {SUMMARY_FILE.name}")
    log(json.dumps(summary, indent=2))
    conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"[49] FATAL: {e}")
        raise
