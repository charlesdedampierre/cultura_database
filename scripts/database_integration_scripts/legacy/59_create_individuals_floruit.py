"""59 — Create individuals_floruit table.

Mirrors `enhance_db/src/bin/59_create_individuals_floruit.rs`.

  Inputs : data/all_humans/all_human_floruit.json
              {qid: {floruit_date: str|null, floruit_precision: int|null}}
  Output : individuals_floruit (wikidata_id PK, floruit_date,
                                  floruit_precision, floruit_year)

Usage
-----
    python3 59_create_individuals_floruit.py
    python3 59_create_individuals_floruit.py --full
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from tqdm import tqdm

from common import (
    ALL_HUMANS_DIR,
    insert_rows,
    load_json,
    log,
    open_db,
    parse_run_mode,
    parse_year,
)

JSON_PATH = ALL_HUMANS_DIR / "all_human_floruit.json"


def run(conn: sqlite3.Connection, json_path: Path = JSON_PATH) -> int:
    log("[DB] 59: Create individuals_floruit...")
    data = load_json(json_path)
    log(f"[DB] {len(data)} floruit entries")

    conn.execute("DROP TABLE IF EXISTS individuals_floruit")
    conn.execute(
        """
        CREATE TABLE individuals_floruit (
            wikidata_id TEXT PRIMARY KEY,
            floruit_date TEXT,
            floruit_precision INTEGER,
            floruit_year INTEGER
        )
        """
    )

    cur = conn.cursor()
    cur.execute("BEGIN")
    n = 0
    bad = 0
    for qid, entry in tqdm(data.items(), desc="59", unit="row"):
        if not isinstance(entry, dict):
            continue
        fdate = entry.get("floruit_date")
        fprec = entry.get("floruit_precision")
        fyear = parse_year(fdate) if fdate else None
        if fdate and fyear is None:
            bad += 1
        cur.execute(
            "INSERT OR REPLACE INTO individuals_floruit "
            "(wikidata_id, floruit_date, floruit_precision, floruit_year) "
            "VALUES (?,?,?,?)",
            (qid, fdate, fprec, fyear),
        )
        n += 1
    conn.commit()
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_floruit_year ON individuals_floruit(floruit_year)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_floruit_precision "
        "ON individuals_floruit(floruit_precision)"
    )
    conn.commit()
    log(f"[DB] inserted {n} (parse failures: {bad})")
    return n


def _sample_main() -> None:
    fake = {
        "Q1": {"floruit_date": "+1450-01-01T00:00:00Z", "floruit_precision": 9},
        "Q2": {"floruit_date": "-0050-01-01T00:00:00Z", "floruit_precision": 7},
        "Q3": {"floruit_date": None, "floruit_precision": None},
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "floruit.json"
        path.write_text(json.dumps(fake))
        db = Path(tmp) / "sample.sqlite3"
        sqlite3.connect(db).close()
        with open_db(db) as conn:
            run(conn, json_path=path)
            for r in conn.execute("SELECT * FROM individuals_floruit"):
                log(f"  {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
