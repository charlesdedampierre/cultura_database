"""62 — Create works table.

Mirrors `enhance_db/src/bin/62_create_works.rs`.

  Inputs : data/all_humans/all_human_works.tsv
              (header + columns: individual_id <TAB> work_id <TAB> relationship)
           data/all_humans/work_labels.json
              {work_qid: english_label}
           individuals (for the joined name_en)
  Output : works (id PK auto, individual_id, individual_name, work_id,
                    work_name, relationship)

Usage
-----
    python3 62_create_works.py
    python3 62_create_works.py --full
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
)

WORKS_TSV = ALL_HUMANS_DIR / "all_human_works.tsv"
LABELS_JSON = ALL_HUMANS_DIR / "work_labels.json"


def run(
    conn: sqlite3.Connection,
    tsv_path: Path = WORKS_TSV,
    labels_path: Path = LABELS_JSON,
) -> int:
    log("[DB] 62: Create works table...")
    work_labels = load_json(labels_path)
    log(f"[DB] {len(work_labels)} work labels")

    indiv_names: dict[str, str] = {}
    for qid, name in conn.execute("SELECT wikidata_id, name_en FROM individuals"):
        if name:
            indiv_names[qid] = name
    log(f"[DB] {len(indiv_names)} individual names loaded")

    conn.execute("DROP TABLE IF EXISTS works")
    conn.execute(
        """
        CREATE TABLE works (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            individual_id TEXT NOT NULL,
            individual_name TEXT,
            work_id TEXT NOT NULL,
            work_name TEXT,
            relationship TEXT NOT NULL
        )
        """
    )

    cur = conn.cursor()
    cur.execute("BEGIN")
    n = 0
    missing_indiv = 0
    missing_label = 0
    with open(tsv_path, "r", encoding="utf-8") as fh:
        fh.readline()  # header
        for line in tqdm(fh, desc="62", unit="line"):
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            iid, wid, rel = parts[0], parts[1], parts[2]
            iname = indiv_names.get(iid)
            if iname is None:
                missing_indiv += 1
            wname = work_labels.get(wid)
            if wname is None:
                missing_label += 1
            cur.execute(
                "INSERT INTO works (individual_id, individual_name, work_id, "
                "work_name, relationship) VALUES (?,?,?,?,?)",
                (iid, iname, wid, wname, rel),
            )
            n += 1
            if n % 100_000 == 0:
                conn.commit()
                cur.execute("BEGIN")
    conn.commit()
    log(f"[DB] inserted {n} (missing indiv: {missing_indiv}, missing label: {missing_label})")

    for sql in (
        "CREATE INDEX IF NOT EXISTS idx_works_individual ON works(individual_id)",
        "CREATE INDEX IF NOT EXISTS idx_works_work ON works(work_id)",
        "CREATE INDEX IF NOT EXISTS idx_works_rel ON works(relationship)",
    ):
        conn.execute(sql)
    conn.commit()
    return n


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tsv = Path(tmp) / "works.tsv"
        tsv.write_text(
            "individual_id\twork_id\trelationship\n"
            "Q1\tQ100\tP50\n"
            "Q1\tQ101\tP170\n"
            "Q2\tQ100\tP86\n"
        )
        labels_path = Path(tmp) / "labels.json"
        labels_path.write_text(json.dumps({
            "Q100": "Magnum Opus", "Q101": "Sonnet 1",
        }))
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, name_en TEXT)"
            )
            insert_rows(seed, "individuals", [
                {"wikidata_id": "Q1", "name_en": "Alice"},
                {"wikidata_id": "Q2", "name_en": "Bob"},
            ])
        with open_db(db) as conn:
            run(conn, tsv_path=tsv, labels_path=labels_path)
            for r in conn.execute(
                "SELECT individual_id, individual_name, work_id, work_name, "
                "relationship FROM works"
            ):
                log(f"  {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
