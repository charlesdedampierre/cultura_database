"""10 — Create the `works` long table from v2 works data.

Inputs : data/all_humans/wikidata_extraction_scripts_v2/works.json
         {human_qid: [{"work": Q..., "prop": P..}, ...]}
         data/all_humans/wikidata_extraction_scripts_v2/work_labels.json
         {work_qid: "English label"}
Output : works (id PK auto, individual_id, individual_name,
                work_id, work_name, relationship)
         - relationship = the property (P50, P170, ...) that linked
           the human to the work.

Usage
-----
    python3 10_create_works.py
    python3 10_create_works.py --full
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import WIKIDATA_V2_DIR, log, load_json, open_db, parse_run_mode


WORKS_PATH = WIKIDATA_V2_DIR / "works.json"
LABELS_PATH = WIKIDATA_V2_DIR / "work_labels.json"


def run(
    conn: sqlite3.Connection,
    works_path: Path = WORKS_PATH,
    labels_path: Path = LABELS_PATH,
) -> int:
    log("[DB] 10: Creating works table...")
    works = load_json(works_path)
    labels = load_json(labels_path) if labels_path.exists() else {}

    name_lookup = {}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='individuals'").fetchone():
        name_lookup = dict(conn.execute("SELECT wikidata_id, name_en FROM individuals"))

    conn.execute("DROP TABLE IF EXISTS works")
    conn.execute(
        """
        CREATE TABLE works (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            individual_id   TEXT NOT NULL,
            individual_name TEXT,
            work_id         TEXT NOT NULL,
            work_name       TEXT,
            relationship    TEXT NOT NULL
        )
        """
    )

    rows = []
    for qid, items in works.items():
        person = name_lookup.get(qid)
        for item in items or []:
            wid = item.get("work")
            if not wid:
                continue
            rows.append((qid, person, wid, labels.get(wid), item.get("prop")))

    conn.executemany(
        "INSERT INTO works (individual_id, individual_name, work_id, work_name, relationship) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_works_individual ON works(individual_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_works_work ON works(work_id)")
    conn.commit()

    log(f"[DB] 10: Inserted {len(rows)} works.")
    return len(rows)


def _sample_main() -> None:
    import json as _json
    fake_works = {
        "Q937": [{"work": "Q41217", "prop": "P50"}, {"work": "Q179356", "prop": "P50"}],
        "Q42":  [{"work": "Q25169", "prop": "P50"}],
    }
    fake_labels = {"Q41217": "Special relativity",
                   "Q179356": "On the Electrodynamics of Moving Bodies",
                   "Q25169": "The Hitchhiker's Guide to the Galaxy"}
    with tempfile.TemporaryDirectory() as tmp:
        wp = Path(tmp) / "works.json"; wp.write_text(_json.dumps(fake_works))
        lp = Path(tmp) / "labels.json"; lp.write_text(_json.dumps(fake_labels))
        with open_db(Path(tmp) / "sample.sqlite3") as conn:
            conn.executescript(
                "CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, name_en TEXT);"
                "INSERT INTO individuals VALUES ('Q937','Albert Einstein'),('Q42','Douglas Adams');"
            )
            n = run(conn, works_path=wp, labels_path=lp)
            for r in conn.execute("SELECT * FROM works ORDER BY id"):
                log(f"  works: {r}")
        log(f"[sample] inserted {n} works")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
