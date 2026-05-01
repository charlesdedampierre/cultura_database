"""49 — Sync wikipedia_url and wikidata_id; apply manual renames.

Mirrors `enhance_db/src/bin/49_sync_polities_from_csv.rs`.

  Inputs : data/manual_changes_cliopatria_data/
                polities_cliopatria_enriched_JSB_iteration.csv
  Output : polities_cliopatria URLs/wikidata_id updated;
           manual rename map applied to both polities_cliopatria
           and cliopatria_polity_periods.

Usage
-----
    python3 49_sync_polities_from_csv.py
    python3 49_sync_polities_from_csv.py --full
"""

from __future__ import annotations

import csv
import sqlite3
import tempfile
from pathlib import Path

from common import DATA_DIR, insert_rows, log, open_db, parse_run_mode

CSV_PATH = DATA_DIR / "manual_changes_cliopatria_data" / \
    "polities_cliopatria_enriched_JSB_iteration.csv"

RENAMES: list[tuple[str, str]] = [
    ("Iragi Republic", "Iraqi Republic"),
    ("Vietnam", "Socialist Republic of Vietnam"),
    ("Champa", "Chámpa"),
    ("Great Việt", "Đại Việt"),
    ("French Colonial Vietnam", "French Indochina"),
    ("Kingdom of Dambadaneiya", "Kingdom of Dambadeniya"),
    ("Gurkha Kingdom", "Gorkha Kingdom"),
]


def _load_csv(path: Path) -> dict[int, dict[str, str]]:
    out: dict[int, dict[str, str]] = {}
    with open(path, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                out[int(row["id"])] = {
                    "vname": row.get("vname", ""),
                    "wikipedia_url": row.get("wikipedia_url", ""),
                    "wikidata_id": row.get("wikidata_id", ""),
                }
            except (KeyError, ValueError):
                continue
    return out


def run(conn: sqlite3.Connection, csv_path: Path = CSV_PATH) -> int:
    log("[DB] 49: Sync URLs / Wikidata IDs and rename polities...")
    csv_rows = _load_csv(csv_path)

    url_updates = []
    wk_updates = []
    for pid, name, db_url, db_wk in conn.execute(
        "SELECT id, name, wikipedia_url, wikidata_id FROM polities_cliopatria"
    ).fetchall():
        c = csv_rows.get(pid)
        if not c:
            continue
        if c["wikipedia_url"] and c["wikipedia_url"] != (db_url or ""):
            url_updates.append((c["wikipedia_url"], pid))
        if c["wikidata_id"] and c["wikidata_id"] != (db_wk or ""):
            wk_updates.append((c["wikidata_id"], pid))

    conn.executemany(
        "UPDATE polities_cliopatria SET wikipedia_url = ? WHERE id = ?", url_updates,
    )
    conn.executemany(
        "UPDATE polities_cliopatria SET wikidata_id = ? WHERE id = ?", wk_updates,
    )
    log(f"[DB] URL updates: {len(url_updates)}, Wikidata updates: {len(wk_updates)}")

    for old, new in RENAMES:
        c1 = conn.execute(
            "UPDATE polities_cliopatria SET name = ? WHERE name = ?", (new, old),
        ).rowcount
        c2 = conn.execute(
            "UPDATE cliopatria_polity_periods SET polity_name = ? WHERE polity_name = ?",
            (new, old),
        ).rowcount
        log(f"  '{old}' -> '{new}' (pc:{c1} pp:{c2})")
    conn.commit()
    return len(url_updates) + len(wk_updates)


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "polities.csv"
        csv_path.write_text(
            "id,vname,wikipedia_url,wikidata_id\n"
            "1,Han Dynasty,http://en.wikipedia.org/Han,Q1\n"
            "2,Iraqi Republic,http://en.wikipedia.org/Iraq,Q2\n"
        )
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE polities_cliopatria (id INTEGER PRIMARY KEY, "
                "name TEXT, wikipedia_url TEXT, wikidata_id TEXT)"
            )
            insert_rows(seed, "polities_cliopatria", [
                {"id": 1, "name": "Han", "wikipedia_url": None, "wikidata_id": None},
                {"id": 2, "name": "Iragi Republic",
                 "wikipedia_url": "old", "wikidata_id": "old"},
            ])
            seed.execute(
                "CREATE TABLE cliopatria_polity_periods "
                "(polity_id INTEGER, polity_name TEXT)"
            )
            insert_rows(seed, "cliopatria_polity_periods", [
                {"polity_id": 2, "polity_name": "Iragi Republic"},
            ])
        with open_db(db) as conn:
            run(conn, csv_path=csv_path)
            for r in conn.execute(
                "SELECT id, name, wikipedia_url, wikidata_id FROM polities_cliopatria"
            ).fetchall():
                log(f"  {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
