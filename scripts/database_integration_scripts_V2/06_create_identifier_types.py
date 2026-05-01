"""06 — Create the `identifier_types` reference table from v2 catalog data.

Inputs : data/all_humans/wikidata_extraction_scripts_v2/catalog_properties.json
         data/all_humans/wikidata_extraction_scripts_v2/catalog_metadata.json
Output : identifier_types (property_id PK, name_en, description, formatter_url,
                           issuer_id, issuer_name, issuer_instance, country_id,
                           country_name, inception, database_records, website)

Usage
-----
    python3 06_create_identifier_types.py
    python3 06_create_identifier_types.py --full
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import WIKIDATA_V2_DIR, log, load_json, open_db, parse_run_mode


PROPS_PATH = WIKIDATA_V2_DIR / "catalog_properties.json"
META_PATH = WIKIDATA_V2_DIR / "catalog_metadata.json"


def run(conn: sqlite3.Connection,
        props_path: Path = PROPS_PATH,
        meta_path: Path = META_PATH) -> int:
    log("[DB] 06: Creating identifier_types table...")

    if props_path.exists():
        props_payload = load_json(props_path)
        props = props_payload.get("properties") if isinstance(props_payload, dict) else props_payload
    else:
        props = []
    meta = load_json(meta_path) if meta_path.exists() else {}

    conn.execute("DROP TABLE IF EXISTS identifier_types")
    conn.execute(
        """
        CREATE TABLE identifier_types (
            property_id TEXT PRIMARY KEY,
            name_en TEXT,
            description TEXT,
            formatter_url TEXT,
            issuer_id TEXT,
            issuer_name TEXT,
            issuer_instance TEXT,
            country_id TEXT,
            country_name TEXT,
            inception TEXT,
            database_records TEXT,
            website TEXT
        )
        """
    )

    rows: dict[str, tuple] = {}
    # base from property list
    for p in props or []:
        pid = p["property_id"]
        rows[pid] = (
            pid, p.get("label"), None, p.get("formatter_url"),
            None, None, None, None, None, None, None, None,
        )
    # enrich from metadata
    for pid, m in (meta or {}).items():
        rows[pid] = (
            pid,
            m.get("label") or (rows.get(pid, (None, None))[1] if pid in rows else None),
            m.get("description"),
            m.get("formatter_url") or (rows.get(pid, (None,) * 4)[3] if pid in rows else None),
            m.get("issuer_id"),
            m.get("issuer_name"),
            m.get("issuer_instance"),
            m.get("country_id"),
            m.get("country_name"),
            m.get("inception"),
            m.get("database_records"),
            m.get("website"),
        )

    conn.executemany(
        "INSERT OR REPLACE INTO identifier_types "
        "(property_id, name_en, description, formatter_url, issuer_id, issuer_name, "
        " issuer_instance, country_id, country_name, inception, database_records, website) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        list(rows.values()),
    )
    conn.commit()
    log(f"[DB] 06: Inserted {len(rows)} identifier types.")
    return len(rows)


def _sample_main() -> None:
    import json as _json
    fake_props = {"properties": [
        {"property_id": "P214", "label": "VIAF", "formatter_url": "https://viaf.org/viaf/$1/"},
        {"property_id": "P227", "label": "GND", "formatter_url": ""},
    ]}
    fake_meta = {
        "P214": {"property_id": "P214", "label": "VIAF cluster ID",
                 "description": "VIAF identifier",
                 "country_id": "Q30", "country_name": "United States",
                 "formatter_url": "https://viaf.org/viaf/$1"},
    }
    with tempfile.TemporaryDirectory() as tmp:
        pp = Path(tmp) / "props.json"; pp.write_text(_json.dumps(fake_props))
        mp = Path(tmp) / "meta.json"; mp.write_text(_json.dumps(fake_meta))
        with open_db(Path(tmp) / "sample.sqlite3") as conn:
            n = run(conn, props_path=pp, meta_path=mp)
            for r in conn.execute("SELECT property_id, name_en, description, country_name FROM identifier_types ORDER BY property_id"):
                log(f"  identifier_types: {r}")
        log(f"[sample] inserted {n} identifier types")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
