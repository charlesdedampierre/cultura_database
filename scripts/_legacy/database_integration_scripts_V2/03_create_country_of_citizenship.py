"""03 — Create the `country_of_citizenship` reference table from v2 metadata.

(Was `nationalities` before the 2026-05 schema change. The table holds
one row per Wikidata QID that any Q5 human declares as a P27
"country of citizenship" value.)

Inputs : data/all_humans/wikidata_extraction_scripts_v2/nationality_metadata.json
         data/all_humans/wikidata_extraction_scripts_v2/nationality_labels.json
Output : country_of_citizenship (wikidata_id PK, name_en, description_en,
                                 instance_of, country_id, replaced_by,
                                 lat, lon, en_wikipedia_url)

Usage
-----
    python3 03_create_country_of_citizenship.py
    python3 03_create_country_of_citizenship.py --full
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
)


META_PATH = WIKIDATA_V2_DIR / "nationality_metadata.json"
LABEL_PATH = WIKIDATA_V2_DIR / "nationality_labels.json"


def run(conn: duckdb.DuckDBPyConnection,
        meta_path: Path = META_PATH,
        label_path: Path = LABEL_PATH) -> int:
    log("[DB] 03: Creating country_of_citizenship table...")

    meta = load_json(meta_path)
    labels = load_json(label_path) if label_path.exists() else {}

    conn.execute("DROP TABLE IF EXISTS country_of_citizenship")
    conn.execute(
        """
        CREATE TABLE country_of_citizenship (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            description_en TEXT,
            instance_of TEXT,
            country_id TEXT,
            replaced_by TEXT,
            lat DOUBLE,
            lon DOUBLE,
            en_wikipedia_url TEXT
        )
        """
    )

    rows = []
    for qid, val in meta.items():
        instances = val.get("instance_of") or []
        replaced = val.get("replaced_by") or []
        rows.append((
            qid,
            val.get("label") or labels.get(qid),
            val.get("description"),
            ",".join(instances) if instances else None,
            val.get("country"),
            ",".join(replaced) if replaced else None,
            val.get("lat"),
            val.get("lon"),
            val.get("en_wikipedia_url"),
        ))

    conn.executemany(
        "INSERT OR IGNORE INTO country_of_citizenship "
        "(wikidata_id, name_en, description_en, instance_of, country_id, "
        " replaced_by, lat, lon, en_wikipedia_url) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coc_name "
        "ON country_of_citizenship(name_en)"
    )

    log(f"[DB] 03: Inserted {len(rows)} country_of_citizenship rows.")
    return len(rows)


def _sample_main() -> None:
    import json as _json
    fake_meta = {
        "Q142": {"id": "Q142", "label": "France", "description": "country in Western Europe",
                 "instance_of": ["Q3624078", "Q6256"], "country": "Q142",
                 "lat": 46.0, "lon": 2.0,
                 "en_wikipedia_url": "https://en.wikipedia.org/wiki/France"},
        "Q145": {"id": "Q145", "label": "United Kingdom",
                 "instance_of": ["Q6256"], "lat": 54.0, "lon": -2.0},
    }
    fake_labels = {"Q142": "France", "Q145": "United Kingdom"}
    with tempfile.TemporaryDirectory() as tmp:
        meta = Path(tmp) / "meta.json"
        labs = Path(tmp) / "labels.json"
        meta.write_text(_json.dumps(fake_meta))
        labs.write_text(_json.dumps(fake_labels))
        sample_db = Path(tmp) / "sample.duckdb"
        with open_db(sample_db) as conn:
            n = run(conn, meta_path=meta, label_path=labs)
            for r in conn.execute(
                "SELECT * FROM country_of_citizenship ORDER BY wikidata_id"
            ).fetchall():
                log(f"  country_of_citizenship: {r}")
        log(f"[sample] inserted {n} rows")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
