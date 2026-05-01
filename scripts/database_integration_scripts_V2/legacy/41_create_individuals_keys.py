"""41 - Create individuals_keys with per-individual Wikidata Q-IDs.

Mirrors `enhance_db/src/bin/41_create_individuals_keys.rs`.

  Inputs : individuals (wikidata_id), plus 6 JSON maps under data/all_humans/:
             all_human_writing_languages.json   list[{id}]
             all_human_deathplaces.json         {id}
             all_human_birthplaces.json         {id}
             all_human_occupations.json         list[str]
             all_human_nationalities.json       list[{id}]
             all_human_genders.json             {id}
  Output : individuals_keys (wikidata_id PK, birthcity_id, deathcity_id,
                              nationalities_ids, occupations_ids, gender_id,
                              writing_language_ids) + 3 indexes.

Note
----
The Rust version uses a streaming serde Visitor to keep memory constant
on multi-GB inputs. The Python port loads each JSON map fully via
`load_json` for simplicity. For the real run on the full pipeline, use
`ijson` (`ijson.kvitems(fh, '')`) to stream entries one-by-one if
memory is tight.

Usage
-----
    python3 41_create_individuals_keys.py            # synthetic
    python3 41_create_individuals_keys.py --full     # real DB + JSON maps
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Callable, Iterable

from tqdm import tqdm

from common import (
    ALL_HUMANS_DIR,
    DB_PATH,
    insert_rows,
    load_json,
    log,
    open_db,
    parse_run_mode,
)

BATCH_SIZE = 50_000


def _stream_update(
    conn: sqlite3.Connection,
    json_path: Path,
    column: str,
    extract: Callable[[object], str | None],
) -> int:
    sql = f"UPDATE individuals_keys SET {column} = ? WHERE wikidata_id = ?"
    log(f"[41] streaming {json_path.name} -> {column}")
    obj = load_json(json_path)
    if not isinstance(obj, dict):
        raise TypeError(f"expected JSON map at {json_path}")
    updated = 0
    buf: list[tuple] = []
    for qid, val in tqdm(obj.items(), desc=f"41:{column}"):
        s = extract(val)
        if s is None:
            continue
        buf.append((s, qid))
        if len(buf) >= BATCH_SIZE:
            conn.executemany(sql, buf)
            conn.commit()
            updated += len(buf)
            buf.clear()
    if buf:
        conn.executemany(sql, buf)
        conn.commit()
        updated += len(buf)
    log(f"[41]   {column}: {updated} rows updated")
    return updated


def _id_obj(val) -> str | None:
    if isinstance(val, dict) and val.get("id"):
        return val["id"]
    return None


def _id_obj_list(val) -> str | None:
    if not isinstance(val, list):
        return None
    ids = [o["id"] for o in val if isinstance(o, dict) and o.get("id")]
    return ";".join(ids) if ids else None


def _str_list(val) -> str | None:
    if not isinstance(val, list) or not val:
        return None
    return ";".join(str(x) for x in val)


def run(conn: sqlite3.Connection, data_dir: Path = ALL_HUMANS_DIR) -> int:
    log("[DB] 41: Creating individuals_keys...")
    conn.execute("DROP TABLE IF EXISTS individuals_keys")
    conn.execute(
        """
        CREATE TABLE individuals_keys (
            wikidata_id TEXT PRIMARY KEY,
            birthcity_id TEXT,
            deathcity_id TEXT,
            nationalities_ids TEXT,
            occupations_ids TEXT,
            gender_id TEXT,
            writing_language_ids TEXT
        )
        """
    )
    inserted = conn.execute(
        "INSERT INTO individuals_keys (wikidata_id) SELECT wikidata_id FROM individuals"
    ).rowcount
    conn.commit()
    log(f"[41] seeded {inserted} wikidata_ids")

    files: Iterable[tuple[str, str, Callable]] = (
        ("all_human_writing_languages.json", "writing_language_ids", _id_obj_list),
        ("all_human_deathplaces.json", "deathcity_id", _id_obj),
        ("all_human_birthplaces.json", "birthcity_id", _id_obj),
        ("all_human_occupations.json", "occupations_ids", _str_list),
        ("all_human_nationalities.json", "nationalities_ids", _id_obj_list),
        ("all_human_genders.json", "gender_id", _id_obj),
    )
    for fname, col, extract in files:
        path = data_dir / fname
        if not path.exists():
            log(f"[41]   skipping {fname} (missing)")
            continue
        _stream_update(conn, path, col, extract)

    for ddl in (
        "CREATE INDEX IF NOT EXISTS idx_ik_birthcity ON individuals_keys(birthcity_id)",
        "CREATE INDEX IF NOT EXISTS idx_ik_deathcity ON individuals_keys(deathcity_id)",
        "CREATE INDEX IF NOT EXISTS idx_ik_gender ON individuals_keys(gender_id)",
    ):
        conn.execute(ddl)
    conn.commit()
    return inserted


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        db = Path(tmp) / "sample.sqlite3"
        (data / "all_human_writing_languages.json").write_text(json.dumps({
            "Q1": [{"id": "Q150"}, {"id": "Q1860"}],
            "Q2": [],
        }))
        (data / "all_human_deathplaces.json").write_text(json.dumps({
            "Q1": {"id": "Q90", "name": "Paris"},
            "Q2": {"id": "Q60", "name": "NYC"},
        }))
        (data / "all_human_birthplaces.json").write_text(json.dumps({
            "Q1": {"id": "Q90", "name": "Paris"},
        }))
        (data / "all_human_occupations.json").write_text(json.dumps({
            "Q1": ["Q170790", "Q188094"],
            "Q2": ["Q36180"],
        }))
        (data / "all_human_nationalities.json").write_text(json.dumps({
            "Q1": [{"id": "Q142"}],
            "Q2": [{"id": "Q30"}],
        }))
        (data / "all_human_genders.json").write_text(json.dumps({
            "Q1": {"id": "Q6581072"},
            "Q2": {"id": "Q6581097"},
        }))
        with sqlite3.connect(db) as seed:
            seed.execute("CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY)")
            insert_rows(seed, "individuals", [
                {"wikidata_id": "Q1"}, {"wikidata_id": "Q2"}, {"wikidata_id": "Q3"},
            ])
        with open_db(db) as conn:
            run(conn, data_dir=data)
            rows = conn.execute("SELECT * FROM individuals_keys").fetchall()
        log(f"[sample] individuals_keys:")
        for r in rows:
            log(f"  {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
