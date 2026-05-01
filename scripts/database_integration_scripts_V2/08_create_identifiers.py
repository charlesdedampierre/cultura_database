"""08 — Create the `identifiers` long table from v2 catalogs.

Inputs : data/all_humans/wikidata_extraction_scripts_v2/catalogs.json
         (the merged {human_qid: {Pxxx: [value, ...]}} map)
Output : identifiers (wikidata_id, individual_name, property_id,
                      identifier_name, value, url) — one row per
                      (human, property, value) triple.

`url` is constructed from `formatter_url` (in identifier_types) by
substituting `$1` with `value`. `individual_name` and `identifier_name`
are looked up in the existing tables for convenience.

Usage
-----
    python3 08_create_identifiers.py
    python3 08_create_identifiers.py --full
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import WIKIDATA_V2_DIR, log, load_json, open_db, parse_run_mode


CATALOGS_PATH = WIKIDATA_V2_DIR / "catalogs.json"


def run(conn: sqlite3.Connection, catalogs_path: Path = CATALOGS_PATH) -> int:
    log("[DB] 08: Creating identifiers table...")
    catalogs = load_json(catalogs_path)

    name_lookup = {}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='individuals'").fetchone():
        name_lookup = dict(conn.execute("SELECT wikidata_id, name_en FROM individuals"))

    type_lookup = {}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='identifier_types'").fetchone():
        type_lookup = {
            r[0]: (r[1], r[2])
            for r in conn.execute("SELECT property_id, name_en, formatter_url FROM identifier_types")
        }

    conn.execute("DROP TABLE IF EXISTS identifiers")
    conn.execute(
        """
        CREATE TABLE identifiers (
            wikidata_id TEXT,
            individual_name TEXT,
            property_id TEXT,
            identifier_name TEXT,
            value TEXT,
            url TEXT,
            PRIMARY KEY (wikidata_id, property_id, value)
        )
        """
    )

    rows = []
    for qid, props in catalogs.items():
        person = name_lookup.get(qid)
        for pid, values in (props or {}).items():
            id_name, formatter = type_lookup.get(pid, (None, None))
            for v in values:
                if not v:
                    continue
                url = formatter.replace("$1", v) if formatter else None
                rows.append((qid, person, pid, id_name, v, url))

    conn.executemany(
        "INSERT OR IGNORE INTO identifiers "
        "(wikidata_id, individual_name, property_id, identifier_name, value, url) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_id_qid ON identifiers(wikidata_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_id_pid ON identifiers(property_id)")
    conn.commit()
    log(f"[DB] 08: Inserted {len(rows)} identifier rows.")
    return len(rows)


def _sample_main() -> None:
    import json as _json
    fake = {
        "Q937": {"P214": ["75121530"], "P227": ["118529579"]},
        "Q42":  {"P214": ["113230702"]},
    }
    with tempfile.TemporaryDirectory() as tmp:
        cp = Path(tmp) / "catalogs.json"; cp.write_text(_json.dumps(fake))
        with open_db(Path(tmp) / "sample.sqlite3") as conn:
            conn.executescript("""
                CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, name_en TEXT);
                CREATE TABLE identifier_types (property_id TEXT PRIMARY KEY, name_en TEXT, formatter_url TEXT);
                INSERT INTO individuals VALUES ('Q937','Albert Einstein'),('Q42','Douglas Adams');
                INSERT INTO identifier_types VALUES
                    ('P214','VIAF','https://viaf.org/viaf/$1/'),
                    ('P227','GND','https://d-nb.info/gnd/$1');
            """)
            n = run(conn, catalogs_path=cp)
            for row in conn.execute("SELECT * FROM identifiers ORDER BY wikidata_id, property_id"):
                log(f"  identifiers: {row}")
        log(f"[sample] inserted {n} identifier rows")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
