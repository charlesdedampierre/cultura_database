"""48 — Rename polities to match the curated CSV.

Mirrors `enhance_db/src/bin/48_rename_polities_from_csv.rs`.

  Inputs : data/manual_changes_cliopatria_data/
                polities_cliopatria_enriched_JSB_iteration.csv
  Output : polities_cliopatria.name and cliopatria_polity_periods.polity_name
           updated to the CSV's `vname` column when they differ.

Usage
-----
    python3 48_rename_polities_from_csv.py
    python3 48_rename_polities_from_csv.py --full
"""

from __future__ import annotations

import csv
import sqlite3
import tempfile
from pathlib import Path

from common import DATA_DIR, insert_rows, log, open_db, parse_run_mode

CSV_PATH = DATA_DIR / "manual_changes_cliopatria_data" / \
    "polities_cliopatria_enriched_JSB_iteration.csv"


def _load_csv(path: Path) -> dict[int, str]:
    out: dict[int, str] = {}
    with open(path, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                out[int(row["id"])] = row["vname"]
            except (KeyError, ValueError):
                continue
    return out


def run(conn: sqlite3.Connection, csv_path: Path = CSV_PATH) -> int:
    log("[DB] 48: Rename polities from CSV...")
    csv_names = _load_csv(csv_path)
    log(f"[DB] Read {len(csv_names)} CSV entries")

    pc_updates = []
    for pid, name in conn.execute("SELECT id, name FROM polities_cliopatria").fetchall():
        if pid in csv_names and csv_names[pid] != name:
            pc_updates.append((csv_names[pid], pid))
            log(f"  pc id={pid}: '{name}' -> '{csv_names[pid]}'")
    conn.executemany(
        "UPDATE polities_cliopatria SET name = ? WHERE id = ?", pc_updates,
    )

    pp_updates = []
    for pid, name in conn.execute(
        "SELECT DISTINCT polity_id, polity_name FROM cliopatria_polity_periods"
    ).fetchall():
        if pid in csv_names and csv_names[pid] != name:
            pp_updates.append((csv_names[pid], pid))
            log(f"  pp id={pid}: '{name}' -> '{csv_names[pid]}'")
    conn.executemany(
        "UPDATE cliopatria_polity_periods SET polity_name = ? WHERE polity_id = ?",
        pp_updates,
    )
    conn.commit()
    log(f"[DB] Updated pc={len(pc_updates)} pp={len(pp_updates)}")
    return len(pc_updates) + len(pp_updates)


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "polities.csv"
        csv_path.write_text(
            "id,vname,wikipedia_url,wikidata_id\n"
            "1,Han Dynasty,http://x,Q1\n"
            "2,Roman Empire,http://y,Q2\n"
        )
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE polities_cliopatria (id INTEGER PRIMARY KEY, name TEXT)"
            )
            insert_rows(seed, "polities_cliopatria", [
                {"id": 1, "name": "Han"},
                {"id": 2, "name": "Rome"},
            ])
            seed.execute(
                "CREATE TABLE cliopatria_polity_periods "
                "(polity_id INTEGER, polity_name TEXT)"
            )
            insert_rows(seed, "cliopatria_polity_periods", [
                {"polity_id": 1, "polity_name": "Han"},
                {"polity_id": 2, "polity_name": "Rome"},
            ])
        with open_db(db) as conn:
            run(conn, csv_path=csv_path)
            for r in conn.execute("SELECT id, name FROM polities_cliopatria").fetchall():
                log(f"  {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
