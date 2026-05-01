"""Helper — Python equivalent of bench_insert_rust.

Mirrors `enhance_db/src/bin/bench_insert_rust.rs`. Reads a TSV and times
how fast Python's sqlite3 can stream inserts in a single transaction
with a prepared statement.

Usage
-----
    python3 helper_bench_insert.py            # tiny synthetic TSV
    python3 helper_bench_insert.py --full     # benchmarks/.../synthetic_works.tsv
"""

from __future__ import annotations

import sqlite3
import tempfile
import time
from pathlib import Path

from common import PROJECT_ROOT, log, parse_run_mode

DEFAULT_TSV = PROJECT_ROOT / "benchmarks" / "sqlite_insert" / "synthetic_works.tsv"
DEFAULT_DB = PROJECT_ROOT / "benchmarks" / "sqlite_insert" / "python.sqlite3"


def fake_indiv_name(qid: str) -> str:
    return f"Individual {qid[1:]}"


def fake_work_name(qid: str) -> str:
    return f"Work {qid[1:]}"


def run(tsv_path: Path = DEFAULT_TSV, db_path: Path = DEFAULT_DB) -> int:
    for ext in ("", "-wal", "-shm"):
        p = Path(str(db_path) + ext)
        if p.exists():
            p.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-2000000")
    conn.execute(
        """
        CREATE TABLE works_bench (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            individual_id TEXT NOT NULL,
            individual_name TEXT,
            work_id TEXT NOT NULL,
            work_name TEXT,
            relationship TEXT NOT NULL
        )
        """
    )

    t0 = time.time()
    n = 0
    with open(tsv_path, "r", encoding="utf-8") as fh:
        fh.readline()  # header
        cur = conn.cursor()
        cur.execute("BEGIN")
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            iid, wid, rel = parts[0], parts[1], parts[2]
            cur.execute(
                "INSERT INTO works_bench (individual_id, individual_name, "
                "work_id, work_name, relationship) VALUES (?,?,?,?,?)",
                (iid, fake_indiv_name(iid), wid, fake_work_name(wid), rel),
            )
            n += 1
        conn.commit()

    elapsed = time.time() - t0
    rate = n / elapsed if elapsed else 0
    log(f"PYTHON: inserted {n} rows in {elapsed:.2f}s ({rate:.0f} rows/s)")
    conn.close()
    return n


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tsv = Path(tmp) / "fake.tsv"
        rows = ["individual_id\twork_id\trelationship\n"]
        for i in range(2000):
            rows.append(f"Q{i}\tQ{i + 100000}\tP50\n")
        tsv.write_text("".join(rows))
        db = Path(tmp) / "bench.sqlite3"
        run(tsv_path=tsv, db_path=db)


if __name__ == "__main__":
    if parse_run_mode() == "full":
        run()
    else:
        _sample_main()
