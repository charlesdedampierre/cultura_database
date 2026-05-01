"""04 — Create the `occupations` reference table from v2 metadata.

Inputs : data/all_humans/wikidata_extraction_scripts_v2/occupation_labels.json
         data/all_humans/wikidata_extraction_scripts_v2/occupation_metadata.json
Output : occupations (id PK, name_en, description_en, instance_of, subclass_of)

Usage
-----
    python3 04_create_occupations.py
    python3 04_create_occupations.py --full
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import WIKIDATA_V2_DIR, log, load_json, open_db, parse_run_mode


LABEL_PATH = WIKIDATA_V2_DIR / "occupation_labels.json"
META_PATH = WIKIDATA_V2_DIR / "occupation_metadata.json"


def run(conn: sqlite3.Connection,
        label_path: Path = LABEL_PATH,
        meta_path: Path = META_PATH) -> int:
    log("[DB] 04: Creating occupations table...")

    labels = load_json(label_path) if label_path.exists() else {}
    meta = load_json(meta_path) if meta_path.exists() else {}

    conn.execute("DROP TABLE IF EXISTS occupations")
    conn.execute(
        """
        CREATE TABLE occupations (
            id TEXT PRIMARY KEY,
            name_en TEXT,
            description_en TEXT,
            instance_of TEXT,
            subclass_of TEXT
        )
        """
    )

    qids = set(labels.keys()) | set(meta.keys())
    rows = []
    for qid in qids:
        m = meta.get(qid, {})
        rows.append((
            qid,
            labels.get(qid),
            m.get("description"),
            ",".join(m.get("instance_of") or []) or None,
            ",".join(m.get("subclass_of") or []) or None,
        ))

    conn.executemany(
        "INSERT OR IGNORE INTO occupations "
        "(id, name_en, description_en, instance_of, subclass_of) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_occ_name ON occupations(name_en)")
    conn.commit()
    log(f"[DB] 04: Inserted {len(rows)} occupations.")
    return len(rows)


def _sample_main() -> None:
    import json as _json
    fake_labels = {"Q36180": "writer", "Q49757": "poet"}
    fake_meta = {
        "Q36180": {"id": "Q36180", "description": "person who uses written words",
                   "instance_of": ["Q28640"], "subclass_of": ["Q482980"]},
        "Q49757": {"id": "Q49757", "description": "person who writes poetry"},
    }
    with tempfile.TemporaryDirectory() as tmp:
        lp = Path(tmp) / "labels.json"; lp.write_text(_json.dumps(fake_labels))
        mp = Path(tmp) / "meta.json"; mp.write_text(_json.dumps(fake_meta))
        with open_db(Path(tmp) / "sample.sqlite3") as conn:
            n = run(conn, label_path=lp, meta_path=mp)
            for r in conn.execute("SELECT * FROM occupations ORDER BY id"):
                log(f"  occupations: {r}")
        log(f"[sample] inserted {n} occupations")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
