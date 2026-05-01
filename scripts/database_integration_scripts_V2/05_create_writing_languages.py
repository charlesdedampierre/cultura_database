"""05 — Create the `writing_languages` reference table from v2 labels.

Inputs : data/all_humans/wikidata_extraction_scripts_v2/writing_language_labels.json
Output : writing_languages (id PK, name_en)

Usage
-----
    python3 05_create_writing_languages.py
    python3 05_create_writing_languages.py --full
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import WIKIDATA_V2_DIR, log, load_json, open_db, parse_run_mode


LABEL_PATH = WIKIDATA_V2_DIR / "writing_language_labels.json"


def run(conn: sqlite3.Connection, label_path: Path = LABEL_PATH) -> int:
    log("[DB] 05: Creating writing_languages table...")
    labels = load_json(label_path)

    conn.execute("DROP TABLE IF EXISTS writing_languages")
    conn.execute(
        "CREATE TABLE writing_languages (id TEXT PRIMARY KEY, name_en TEXT)"
    )
    conn.executemany(
        "INSERT OR IGNORE INTO writing_languages (id, name_en) VALUES (?, ?)",
        list(labels.items()),
    )
    conn.commit()
    log(f"[DB] 05: Inserted {len(labels)} writing languages.")
    return len(labels)


def _sample_main() -> None:
    import json as _json
    fake = {"Q1860": "English", "Q150": "French", "Q188": "German"}
    with tempfile.TemporaryDirectory() as tmp:
        lp = Path(tmp) / "labels.json"; lp.write_text(_json.dumps(fake))
        with open_db(Path(tmp) / "sample.sqlite3") as conn:
            n = run(conn, label_path=lp)
            for r in conn.execute("SELECT * FROM writing_languages ORDER BY id"):
                log(f"  writing_languages: {r}")
        log(f"[sample] inserted {n} languages")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
