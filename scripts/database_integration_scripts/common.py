"""Shared helpers for the v2 integration pipeline.

Each script under this directory writes one table directly into a fresh
DuckDB file (``data/humans_v2.duckdb`` by default). There is no SQLite
intermediate any more — DuckDB is now the canonical storage format end
to end.

The shared helpers in this module mirror the small set of patterns the
scripts share: opening the DB with sensible session settings, batched
``executemany`` with tqdm progress, JSON loading, year parsing, and a
``--full`` / ``--sample`` CLI mode.
"""

from __future__ import annotations

import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

import duckdb

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw_data_from_wikidata"
ALL_HUMANS_DIR = RAW_DATA_DIR  # backwards-compatible alias

# Where the v2 extraction JSONs live. Override with `WIKIDATA_V2_DIR` env
# var when running against the test cohort (test_1000) or any other slice.
WIKIDATA_V2_DIR = (
    Path(os.environ["WIKIDATA_V2_DIR"])
    if os.environ.get("WIKIDATA_V2_DIR")
    else RAW_DATA_DIR
)
WIKIDATA_TEST_DIR = RAW_DATA_DIR / "test_1000"

# `CULTURA_DB_PATH` env var overrides DB_PATH so the v2 scripts can be
# pointed at, e.g., a fresh humans_test.duckdb without modifying common.py.
DB_PATH = (
    Path(os.environ["CULTURA_DB_PATH"])
    if os.environ.get("CULTURA_DB_PATH")
    else DATA_DIR / "humans_v2.duckdb"
)
SAMPLE_DB_PATH = DATA_DIR / "humans_v2.sample.duckdb"

# Read-only reference to the canonical DuckDB. Never written by this pipeline.
LEGACY_DB_PATH = DATA_DIR / "humans_clean.duckdb"

TASK_LOG = PROJECT_ROOT / "task.log"

DEFAULT_BATCH = 50_000


# --------------------------------------------------------------------------
# Logging
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
# DuckDB connection helpers
# --------------------------------------------------------------------------


def open_db(
    db_path: Path | str = DB_PATH,
    *,
    read_only: bool = False,
    threads: int | None = None,
) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection. Returns the connection (use as ctx manager)."""
    con = duckdb.connect(str(db_path), read_only=read_only)
    if threads is not None:
        con.execute(f"PRAGMA threads={int(threads)}")
    con.execute("PRAGMA enable_progress_bar=false")
    return con


def column_exists(conn: duckdb.DuckDBPyConnection, table: str, column: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema='main' AND table_name=? AND column_name=?",
        [table, column],
    ).fetchone()
    return row is not None


def table_exists(conn: duckdb.DuckDBPyConnection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='main' AND table_name=?",
        [table],
    ).fetchone()
    return row is not None


def add_column_if_missing(
    conn: duckdb.DuckDBPyConnection, table: str, column: str, decl: str
) -> bool:
    if column_exists(conn, table, column):
        return False
    conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {decl}')
    return True


def row_count(conn: duckdb.DuckDBPyConnection, table: str) -> int:
    return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]


# --------------------------------------------------------------------------
# Encoding fix (rare in the v2 pipeline; kept for legacy parity)
# --------------------------------------------------------------------------


def fix_mojibake(text: str | None) -> str | None:
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
    obj = load_json(path)
    if not isinstance(obj, dict):
        raise TypeError(f"Expected a JSON object at {path}")
    yield from obj.items()


# --------------------------------------------------------------------------
# Transactions and batched inserts
# --------------------------------------------------------------------------


@contextmanager
def transaction(conn: duckdb.DuckDBPyConnection):
    """`with transaction(conn):` — commits on success, rollbacks on error."""
    conn.execute("BEGIN TRANSACTION")
    try:
        yield
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def executemany_batched(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    rows: Iterable[tuple],
    *,
    batch_size: int = DEFAULT_BATCH,
    desc: str | None = None,
    total: int | None = None,
) -> int:
    """Execute `sql` over `rows` in transactions of `batch_size`. Returns count."""
    try:
        from tqdm import tqdm

        iterator = tqdm(rows, total=total, desc=desc, unit="row")
    except ImportError:
        iterator = rows

    n = 0
    buf: list[tuple] = []
    for row in iterator:
        buf.append(row)
        if len(buf) >= batch_size:
            with transaction(conn):
                conn.executemany(sql, buf)
            n += len(buf)
            buf.clear()
    if buf:
        with transaction(conn):
            conn.executemany(sql, buf)
        n += len(buf)
    return n


# --------------------------------------------------------------------------
# Date / year parsing
# --------------------------------------------------------------------------


def parse_year(s: str | None) -> int | None:
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
# Sample / probe helpers
# --------------------------------------------------------------------------


def parse_run_mode() -> str:
    """Return "full" if `--full` is passed, else "sample"."""
    return "full" if "--full" in sys.argv[1:] else "sample"


def insert_rows(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    rows: Iterable[dict[str, Any]],
) -> int:
    rows = list(rows)
    if not rows:
        return 0
    cols = list(rows[0].keys())
    col_csv = ",".join(f'"{c}"' for c in cols)
    placeholders = ",".join("?" * len(cols))
    conn.executemany(
        f'INSERT INTO "{table}" ({col_csv}) VALUES ({placeholders})',
        [tuple(r[c] for c in cols) for r in rows],
    )
    return len(rows)


def temp_db(name: str = "_sample.duckdb") -> Path:
    return Path(__file__).resolve().parent / name


def stopwatch():
    t0 = time.time()
    return lambda: time.time() - t0


__all__ = [
    "PROJECT_ROOT",
    "DATA_DIR",
    "RAW_DATA_DIR",
    "ALL_HUMANS_DIR",
    "WIKIDATA_V2_DIR",
    "WIKIDATA_TEST_DIR",
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
