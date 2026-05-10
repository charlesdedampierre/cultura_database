"""11 — Create the `individual_writing_languages` long table.

Inputs : data/all_humans/wikidata_extraction_scripts_v2/writing_languages.json
         {human_qid: [language_qid, ...]}
Output : individual_writing_languages (wikidata_id, individual_name,
                                       language_id, language_name)
         PK (wikidata_id, language_id).

Usage
-----
    python3 11_create_individual_writing_languages.py
    python3 11_create_individual_writing_languages.py --full
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


JSON_PATH = WIKIDATA_V2_DIR / "writing_languages.json"


def run(conn: duckdb.DuckDBPyConnection, json_path: Path = JSON_PATH) -> int:
    log("[DB] 11: Creating individual_writing_languages table...")
    data = load_json(json_path)

    name_lookup: dict[str, str] = {}
    if table_exists(conn, "individuals"):
        name_lookup = dict(conn.execute("SELECT wikidata_id, name_en FROM individuals").fetchall())
    lang_lookup: dict[str, str] = {}
    if table_exists(conn, "writing_languages"):
        lang_lookup = dict(conn.execute("SELECT id, name_en FROM writing_languages").fetchall())

    conn.execute("DROP TABLE IF EXISTS individual_writing_languages")
    conn.execute(
        """
        CREATE TABLE individual_writing_languages (
            wikidata_id TEXT NOT NULL,
            individual_name TEXT,
            language_id TEXT NOT NULL,
            language_name TEXT,
            PRIMARY KEY (wikidata_id, language_id)
        )
        """
    )

    rows = []
    for qid, langs in data.items():
        for lid in langs or []:
            rows.append((qid, name_lookup.get(qid), lid, lang_lookup.get(lid)))

    conn.executemany(
        "INSERT OR IGNORE INTO individual_writing_languages "
        "(wikidata_id, individual_name, language_id, language_name) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    log(f"[DB] 11: Inserted {len(rows)} (individual, language) pairs.")
    return len(rows)


def _sample_main() -> None:
    import json as _json
    fake = {"Q937": ["Q188"], "Q42": ["Q1860"]}
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "writing_languages.json"; p.write_text(_json.dumps(fake))
        with open_db(Path(tmp) / "sample.duckdb") as conn:
            conn.execute("CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, name_en TEXT)")
            conn.execute("CREATE TABLE writing_languages (id TEXT PRIMARY KEY, name_en TEXT)")
            conn.execute("INSERT INTO individuals VALUES ('Q937','Albert Einstein'),('Q42','Douglas Adams')")
            conn.execute("INSERT INTO writing_languages VALUES ('Q188','German'),('Q1860','English')")
            n = run(conn, json_path=p)
            for r in conn.execute("SELECT * FROM individual_writing_languages ORDER BY wikidata_id").fetchall():
                log(f"  individual_writing_languages: {r}")
        log(f"[sample] inserted {n} pairs")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
