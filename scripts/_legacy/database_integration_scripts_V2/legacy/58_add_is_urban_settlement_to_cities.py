"""58 — Add is_urban_settlement to cities.

Mirrors `enhance_db/src/bin/58_add_is_urban_settlement_to_cities.rs`.

  Inputs : data/all_humans/entity_type_classification.json
              {qid: {urban_settlement: bool, ...}}
           cities.entity_type_ids   (pipe-joined Q-ids from step 57)
  Output : cities.is_urban_settlement (1 / 0 / NULL)

Usage
-----
    python3 58_add_is_urban_settlement_to_cities.py
    python3 58_add_is_urban_settlement_to_cities.py --full
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

JSON_PATH = ALL_HUMANS_DIR / "entity_type_classification.json"


def run(conn: sqlite3.Connection, json_path: Path = JSON_PATH) -> int:
    log("[DB] 58: Add is_urban_settlement to cities...")
    raw = load_json(json_path)
    urban_ids: set[str] = {
        k for k, v in raw.items()
        if isinstance(v, dict) and v.get("urban_settlement") is True
    }
    log(f"[DB] {len(urban_ids)} urban P31 ids")

    add_column_if_missing(conn, "cities", "is_urban_settlement", "INTEGER")
    conn.execute("UPDATE cities SET is_urban_settlement = NULL")
    conn.commit()

    rows = list(conn.execute("SELECT id, entity_type_ids FROM cities"))
    cur = conn.cursor()
    urban = 0
    non_urban = 0
    null_n = 0
    for qid, etypes in tqdm(rows, desc="58", unit="city"):
        if not etypes:
            null_n += 1
            val = None
        else:
            val = 1 if any(t in urban_ids for t in etypes.split("|")) else 0
            if val == 1:
                urban += 1
            else:
                non_urban += 1
        cur.execute(
            "UPDATE cities SET is_urban_settlement = ? WHERE id = ?",
            (val, qid),
        )
    conn.commit()
    log(f"[DB] urban={urban} non_urban={non_urban} null={null_n}")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cities_is_urban_settlement "
        "ON cities(is_urban_settlement)"
    )
    conn.commit()
    return urban


def _sample_main() -> None:
    classification = {
        "Q515": {"urban_settlement": True},
        "Q174844": {"urban_settlement": True},
        "Q3957": {"urban_settlement": False},
    }
    with tempfile.TemporaryDirectory() as tmp:
        json_path = Path(tmp) / "classification.json"
        json_path.write_text(json.dumps(classification))
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE cities (id TEXT PRIMARY KEY, name_en TEXT, "
                "entity_type_ids TEXT)"
            )
            insert_rows(seed, "cities", [
                {"id": "Q90", "name_en": "Paris", "entity_type_ids": "Q515|Q174844"},
                {"id": "Q1234", "name_en": "Village", "entity_type_ids": "Q3957"},
                {"id": "Q777", "name_en": "Mystery", "entity_type_ids": None},
            ])
        with open_db(db) as conn:
            run(conn, json_path=json_path)
            for r in conn.execute(
                "SELECT id, name_en, is_urban_settlement FROM cities"
            ):
                log(f"  {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
