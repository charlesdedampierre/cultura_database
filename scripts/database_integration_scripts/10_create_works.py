"""10 — Create the `works` long table from v2 works data.

Inputs : data/all_humans/wikidata_extraction_scripts_v2/works.json
         {human_qid: [{"work": Q..., "prop": P..}, ...]}
         data/all_humans/wikidata_extraction_scripts_v2/work_labels.json
         {work_qid: "English label"}
Output : works (id PK auto, individual_id, individual_name,
                work_id, work_name, relationship)
         - relationship = a human-readable role name ("author",
           "director", "composer", ...). The original Wikidata P-id
           for each role is recorded in
           `wikidata_properties_definition`.

Usage
-----
    python3 10_create_works.py
    python3 10_create_works.py --full
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import duckdb

from common import (
    WIKIDATA_V2_DIR,
    log,
    load_json,
    open_db,
    parse_run_mode,
    table_exists,
)


WORKS_PATH = WIKIDATA_V2_DIR / "works.json"
LABELS_PATH = WIKIDATA_V2_DIR / "work_labels.json"

RELATIONSHIP_BY_PID = {
    "P50":  "author",
    "P57":  "director",
    "P58":  "screenwriter",
    "P86":  "composer",
    "P98":  "editor",
    "P110": "illustrator",
    "P162": "producer",
    "P170": "creator",
    "P175": "performer",
}


def relationship_name(prop: str | None) -> str | None:
    if not prop:
        return None
    return RELATIONSHIP_BY_PID.get(prop, prop)


def run(
    conn: duckdb.DuckDBPyConnection,
    works_path: Path = WORKS_PATH,
    labels_path: Path = LABELS_PATH,
) -> int:
    log("[DB] 10: Creating works table...")
    works = load_json(works_path)
    labels = load_json(labels_path) if labels_path.exists() else {}

    name_lookup: dict[str, str] = {}
    if table_exists(conn, "individuals"):
        name_lookup = dict(conn.execute("SELECT wikidata_id, name_en FROM individuals").fetchall())

    conn.execute("DROP TABLE IF EXISTS works")
    conn.execute("DROP SEQUENCE IF EXISTS seq_works_id")
    conn.execute("CREATE SEQUENCE seq_works_id START 1")
    conn.execute(
        """
        CREATE TABLE works (
            id BIGINT PRIMARY KEY DEFAULT nextval('seq_works_id'),
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
            rows.append((qid, person, wid, labels.get(wid),
                         relationship_name(item.get("prop"))))

    conn.executemany(
        "INSERT INTO works (individual_id, individual_name, work_id, work_name, relationship) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_works_individual ON works(individual_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_works_work ON works(work_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_works_rel ON works(relationship)")

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
        with open_db(Path(tmp) / "sample.duckdb") as conn:
            conn.execute("CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, name_en TEXT)")
            conn.execute(
                "INSERT INTO individuals VALUES ('Q937','Albert Einstein'),('Q42','Douglas Adams')"
            )
            n = run(conn, works_path=wp, labels_path=lp)
            for r in conn.execute("SELECT * FROM works ORDER BY id").fetchall():
                log(f"  works: {r}")
        log(f"[sample] inserted {n} works")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
