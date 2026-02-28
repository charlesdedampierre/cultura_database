"""Database connection for the visualizer."""

import sqlite3
import threading
from pathlib import Path
from contextlib import contextmanager


# Path to the light database
DB_PATH = Path(__file__).parent.parent / "data" / "visualizer.sqlite3"

# Thread-local storage for connections
_local = threading.local()


def get_db_connection():
    """Get a thread-local database connection with row factory."""
    if not hasattr(_local, 'conn') or _local.conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.text_factory = lambda b: b.decode('utf-8', errors='replace')
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        _local.conn = conn
    return _local.conn


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = get_db_connection()
    try:
        yield conn
    finally:
        pass  # Keep connection alive in thread-local storage


def dict_from_row(row):
    """Convert sqlite3.Row to dict."""
    return dict(row) if row else None


def dicts_from_rows(rows):
    """Convert list of sqlite3.Row to list of dicts."""
    return [dict(row) for row in rows]
