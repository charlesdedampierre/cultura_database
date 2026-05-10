"""57 — Add entity_type / entity_type_ids to cities.

Mirrors `enhance_db/src/bin/57_add_entity_type_to_cities.rs`.

  Inputs : data/all_humans/city_entity_types.json
              {qid: {types: [{id: Q..., label: ...}, ...]}}
  Output : cities.entity_type     (pipe-joined English labels)
           cities.entity_type_ids (pipe-joined Wikidata Q-ids)

Usage
-----
    python3 57_add_entity_type_to_cities.py
    python3 57_add_entity_type_to_cities.py --full
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from tqdm import tqdm

from common import (
    ALL_HUMANS_DIR,
    add_column_if_missing,
    insert_rows,
    load_json,
    log,
    open_db,
    parse_run_mode,
)

JSON_PATH = ALL_HUMANS_DIR / "city_entity_types.json"


def run(conn: sqlite3.Connection, json_path: Path = JSON_PATH) -> int:
    log("[DB] 57: Add entity_type to cities...")
    types_map = load_json(json_path)
    log(f"[DB] {len(types_map)} cities with P31 data")

    add_column_if_missing(conn, "cities", "entity_type", "TEXT")
    add_column_if_missing(conn, "cities", "entity_type_ids", "TEXT")
    conn.execute("UPDATE cities SET entity_type = NULL, entity_type_ids = NULL")
    conn.commit()

    cur = conn.cursor()
    updated = 0
    for qid, val in tqdm(types_map.items(), desc="57", unit="city"):
        types = val.get("types") if isinstance(val, dict) else None
        if not types:
            continue
        labels: list[str] = []
        ids: list[str] = []
        for t in types:
            tid = (t.get("id") or "").strip()
            label = (t.get("label") or "").strip()
            if not tid:
                continue
            ids.append(tid)
            labels.append(label or tid)
        if not ids:
            continue
        cur.execute(
            "UPDATE cities SET entity_type = ?, entity_type_ids = ? WHERE id = ?",
            ("|".join(labels), "|".join(ids), qid),
        )
        updated += cur.rowcount
    conn.commit()
    log(f"[DB] updated {updated} cities")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cities_entity_type ON cities(entity_type)"
    )
    conn.commit()
    return updated


def _sample_main() -> None:
    fake = {
        "Q90": {"types": [
            {"id": "Q515", "label": "city"},
            {"id": "Q174844", "label": "megacity"},
        ]},
        "Q60": {"types": [{"id": "Q515", "label": "city"}]},
        "Q777": {"types": []},
    }
    with tempfile.TemporaryDirectory() as tmp:
        json_path = Path(tmp) / "city_entity_types.json"
        json_path.write_text(json.dumps(fake))
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE cities (id TEXT PRIMARY KEY, name_en TEXT)"
            )
            insert_rows(seed, "cities", [
                {"id": "Q90", "name_en": "Paris"},
                {"id": "Q60", "name_en": "New York"},
                {"id": "Q777", "name_en": "Mystery"},
            ])
        with open_db(db) as conn:
            run(conn, json_path=json_path)
            for r in conn.execute(
                "SELECT id, name_en, entity_type, entity_type_ids FROM cities"
            ):
                log(f"  {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
