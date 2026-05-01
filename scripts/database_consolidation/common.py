"""Shared helpers for the Python port of the Rust enrichment pipeline.

The Rust scripts under `enhance_db/src/bin/` all share a small set of
patterns: open the SQLite database with WAL pragmas, append progress
messages to `task.log`, stream JSON / TSV inputs from
`data/all_humans/`, and bulk-update the database in batched
transactions with a tqdm-style progress bar.

This module centralises those patterns so each numbered script stays
short and focused on its own SQL.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
ALL_HUMANS_DIR = DATA_DIR / "all_humans"

# v2 wikidata extraction outputs — this is what the simplified scripts read.
WIKIDATA_V2_DIR = ALL_HUMANS_DIR / "wikidata_extraction_scripts_v2"

# IMPORTANT: the canonical v1 database `humans_clean.sqlite3` is never written
# to by this pipeline. The simplified v2 build always materialises a fresh
# `humans_v2.sqlite3`. This protects the user's existing DB from accidental
# overwrites and lets the v2 build be re-run end-to-end at any time.
LEGACY_DB_PATH = DATA_DIR / "humans_clean.sqlite3"
DB_PATH = DATA_DIR / "humans_v2.sqlite3"
SAMPLE_DB_PATH = DATA_DIR / "humans_v2.sample.sqlite3"

TASK_LOG = PROJECT_ROOT / "task.log"

DEFAULT_BATCH = 50_000


# --------------------------------------------------------------------------
# Logging (mirrors the Rust `log()` helper)
# --------------------------------------------------------------------------

def log(msg: str) -> None:
    """Print to stdout and append to task.log (best-effort)."""
    print(msg, flush=True)
    try:
        with open(TASK_LOG, "a") as fh:
            fh.write(msg + "\n")
    except OSError:
        pass


# --------------------------------------------------------------------------
# SQLite connection helpers
# --------------------------------------------------------------------------

def open_db(
    db_path: Path | str = DB_PATH,
    *,
    cache_mb: int = 2_000,
    read_only: bool = False,
) -> sqlite3.Connection:
    """Open SQLite with the same pragmas the Rust scripts use."""
    db_path = str(db_path)
    if read_only:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(f"PRAGMA cache_size=-{cache_mb * 1000}")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, decl: str
) -> bool:
    if column_exists(conn, table, column):
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    conn.commit()
    return True


def row_count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# --------------------------------------------------------------------------
# Encoding fix (mirrors Rust 02_fix_encoding logic)
# --------------------------------------------------------------------------

def fix_mojibake(text: str | None) -> str | None:
    """Try to recover a string that was written as Latin-1-encoded UTF-8.

    Returns the fixed string if a fix was applied, otherwise None (so
    callers can skip rows that were already clean).
    """
    if not text:
        return None
    if not any(0xC0 <= ord(c) <= 0xFF for c in text):
        return None
    if any(ord(c) > 0xFF for c in text):
        return None
    try:
        fixed = bytes(ord(c) for c in text).decode("utf-8")
    except UnicodeDecodeError:
        return None
    return fixed if fixed != text else None


# --------------------------------------------------------------------------
# JSON helpers
# --------------------------------------------------------------------------

def load_json(path: Path | str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def iter_json_map(path: Path | str) -> Iterator[tuple[str, Any]]:
    """Yield (key, value) from a JSON map. Loads the whole file (simple).

    For very large files where memory matters, callers can swap in
    `ijson` instead — keep this helper for the common < 1 GB case.
    """
    obj = load_json(path)
    if not isinstance(obj, dict):
        raise TypeError(f"Expected a JSON object at {path}")
    yield from obj.items()


# --------------------------------------------------------------------------
# Batched transactions
# --------------------------------------------------------------------------

@contextmanager
def transaction(conn: sqlite3.Connection):
    """`with transaction(conn):` — commits on success, rollbacks on error."""
    try:
        yield
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def executemany_batched(
    conn: sqlite3.Connection,
    sql: str,
    rows: Iterable[tuple],
    *,
    batch_size: int = DEFAULT_BATCH,
    desc: str | None = None,
    total: int | None = None,
) -> int:
    """Execute `sql` over `rows` in transactions of `batch_size`.

    Returns the number of rows processed. Wraps tqdm if available.
    """
    try:
        from tqdm import tqdm

        iterator = tqdm(rows, total=total, desc=desc, unit="row")
    except ImportError:
        iterator = rows

    n = 0
    buf: list[tuple] = []
    cur = conn.cursor()
    for row in iterator:
        buf.append(row)
        if len(buf) >= batch_size:
            with transaction(conn):
                cur.executemany(sql, buf)
            n += len(buf)
            buf.clear()
    if buf:
        with transaction(conn):
            cur.executemany(sql, buf)
        n += len(buf)
    return n


# --------------------------------------------------------------------------
# Date / year parsing (used by impact_date, regions, floruit, cliopatria)
# --------------------------------------------------------------------------

def parse_year(s: str | None) -> int | None:
    """Pull the integer year out of an ISO date string.

    Handles BCE years prefixed with `-`, blank-node placeholders, and
    plain year strings ("1850").
    """
    if not s:
        return None
    s = s.strip()
    if not s or s.startswith("_:"):
        return None
    sign = 1
    if s.startswith("-"):
        sign = -1
        s = s[1:]
    elif s.startswith("+"):
        s = s[1:]
    head = s.split("-", 1)[0].split("T", 1)[0]
    try:
        return sign * int(head)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Sample / probe helpers used by the per-script `__main__` blocks
# --------------------------------------------------------------------------

def parse_run_mode() -> str:
    """Parse the `--full` / `--sample` switch.

    Returns "full" when the caller wants to run against the real
    `data/humans_clean.sqlite3`. Returns "sample" otherwise — each
    script's `__main__` is expected to build a tiny synthetic DB.
    """
    argv = sys.argv[1:]
    if "--full" in argv:
        return "full"
    return "sample"


def insert_rows(
    conn: sqlite3.Connection,
    table: str,
    rows: Iterable[dict[str, Any]],
) -> int:
    """Convenience: dict-row insert. Used by `__main__` blocks to
    seed synthetic data without writing the column list twice.
    """
    rows = list(rows)
    if not rows:
        return 0
    cols = list(rows[0].keys())
    col_csv = ",".join(cols)
    placeholders = ",".join("?" * len(cols))
    conn.executemany(
        f"INSERT INTO {table} ({col_csv}) VALUES ({placeholders})",
        [tuple(r[c] for c in cols) for r in rows],
    )
    return len(rows)


def temp_db(name: str = "_sample.sqlite3") -> Path:
    """Path to a per-script throwaway DB next to this module."""
    return Path(__file__).resolve().parent / name


def stopwatch():
    """Return a () -> elapsed-seconds closure."""
    t0 = time.time()
    return lambda: time.time() - t0


__all__ = [
    "PROJECT_ROOT",
    "DATA_DIR",
    "ALL_HUMANS_DIR",
    "WIKIDATA_V2_DIR",
    "LEGACY_DB_PATH",
    "DB_PATH",
    "SAMPLE_DB_PATH",
    "TASK_LOG",
    "DEFAULT_BATCH",
    "log",
    "open_db",
    "column_exists",
    "table_exists",
    "add_column_if_missing",
    "row_count",
    "fix_mojibake",
    "load_json",
    "iter_json_map",
    "transaction",
    "executemany_batched",
    "parse_year",
    "parse_run_mode",
    "insert_rows",
    "temp_db",
    "stopwatch",
]
