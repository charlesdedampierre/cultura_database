"""12 — Create the `individuals_floruit` table from v2 main_info + precision.

Stores the *raw* floruit fact (P1317) per Q5 plus its precision and
parsed year. The downstream "floruit period" derivation (start..end
window with century fallback) lives in
`scripts/database_consolidation/01_individuals_floruit_period.py`.

Inputs : data/all_humans/wikidata_extraction_scripts_v2/main_info.json
         data/all_humans/wikidata_extraction_scripts_v2/date_precisions.json
Output : individuals_floruit (wikidata_id PK, floruit_date, floruit_precision,
                              floruit_year)

Usage
-----
    python3 12_create_individuals_floruit.py
    python3 12_create_individuals_floruit.py --full
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import (
    WIKIDATA_V2_DIR,
    log,
    load_json,
    open_db,
    parse_run_mode,
    parse_year,
)


MAIN_PATH = WIKIDATA_V2_DIR / "main_info.json"
PREC_PATH = WIKIDATA_V2_DIR / "date_precisions.json"


def run(
    conn: sqlite3.Connection,
    main_path: Path = MAIN_PATH,
    prec_path: Path = PREC_PATH,
) -> int:
    log("[DB] 12: Creating individuals_floruit table...")
    main = load_json(main_path)
    precisions = load_json(prec_path) if prec_path.exists() else {}

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

    rows = []
    for qid, m in main.items():
        floruit = m.get("floruit")
        if not floruit:
            continue
        prec = (precisions.get(qid) or {}).get("floruit_precision")
        rows.append((qid, floruit, prec, parse_year(floruit)))

    conn.executemany(
        "INSERT OR IGNORE INTO individuals_floruit "
        "(wikidata_id, floruit_date, floruit_precision, floruit_year) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_floruit_year ON individuals_floruit(floruit_year)")
    conn.commit()

    log(f"[DB] 12: Inserted {len(rows)} floruit rows.")
    return len(rows)


def _sample_main() -> None:
    import json as _json
    fake_main = {
        "Q1": {"id": "Q1", "name": "alpha", "floruit": "1450-01-01T00:00:00Z"},
        "Q2": {"id": "Q2", "name": "beta",  "floruit": "0480-01-01T00:00:00Z"},
        "Q3": {"id": "Q3", "name": "gamma"},  # no floruit -> skipped
    }
    fake_prec = {
        "Q1": {"floruit_precision": 9},
        "Q2": {"floruit_precision": 7},
    }
    with tempfile.TemporaryDirectory() as tmp:
        mp = Path(tmp) / "main.json"; mp.write_text(_json.dumps(fake_main))
        pp = Path(tmp) / "prec.json"; pp.write_text(_json.dumps(fake_prec))
        with open_db(Path(tmp) / "sample.sqlite3") as conn:
            n = run(conn, main_path=mp, prec_path=pp)
            for r in conn.execute("SELECT * FROM individuals_floruit ORDER BY wikidata_id"):
                log(f"  individuals_floruit: {r}")
        log(f"[sample] inserted {n} floruit rows")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
