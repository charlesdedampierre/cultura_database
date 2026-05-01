"""38 - Copy polity_periods from cliopatria.db to humans_clean.

Mirrors `enhance_db/src/bin/38_copy_polity_periods.rs`.

  Inputs : cliopatria.db / polity_periods (id, polity_id, polity_name,
           from_year, to_year, area, geometry)
  Output : cliopatria_polity_periods (same columns) + 2 indexes.

Usage
-----
    python3 38_copy_polity_periods.py            # synthetic
    python3 38_copy_polity_periods.py --full     # real DB
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import PROJECT_ROOT, insert_rows, log, open_db, parse_run_mode

CLIO_DB_PATH = PROJECT_ROOT / "cliopatria_data" / "processing" / "data" / "cliopatria.db"


def run(conn: sqlite3.Connection, clio_db_path: Path | str = CLIO_DB_PATH) -> int:
    log("[DB] 38: Copying polity_periods...")
    conn.execute("DROP TABLE IF EXISTS cliopatria_polity_periods")
    conn.execute(
        """
        CREATE TABLE cliopatria_polity_periods (
            id INTEGER PRIMARY KEY,
            polity_id INTEGER NOT NULL,
            polity_name TEXT,
            from_year INTEGER,
            to_year INTEGER,
            area REAL,
            geometry TEXT
        )
        """
    )
    with sqlite3.connect(str(clio_db_path)) as clio:
        rows = clio.execute(
            "SELECT id, polity_id, polity_name, from_year, to_year, area, geometry "
            "FROM polity_periods"
        ).fetchall()
    conn.executemany(
        "INSERT INTO cliopatria_polity_periods "
        "(id, polity_id, polity_name, from_year, to_year, area, geometry) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cpp_polity_id ON cliopatria_polity_periods(polity_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cpp_years ON cliopatria_polity_periods(from_year, to_year)"
    )
    conn.commit()
    log(f"[38] copied {len(rows)} rows")
    return len(rows)


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        clio = Path(tmp) / "clio.db"
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(clio) as c:
            c.execute(
                "CREATE TABLE polity_periods (id INTEGER, polity_id INTEGER, polity_name TEXT, "
                "from_year INTEGER, to_year INTEGER, area REAL, geometry TEXT)"
            )
            insert_rows(c, "polity_periods", [
                {"id": 1, "polity_id": 1, "polity_name": "France", "from_year": 1500,
                 "to_year": 1789, "area": 500000.0, "geometry": '{"type":"Polygon","coordinates":[]}'},
                {"id": 2, "polity_id": 2, "polity_name": "British Empire", "from_year": 1700,
                 "to_year": 1947, "area": 35000000.0, "geometry": '{"type":"Polygon","coordinates":[]}'},
            ])
        with open_db(db) as conn:
            n = run(conn, clio_db_path=clio)
            rows = conn.execute("SELECT id, polity_name, from_year, to_year FROM cliopatria_polity_periods").fetchall()
        log(f"[sample] {n} rows")
        for r in rows:
            log(f"  {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
