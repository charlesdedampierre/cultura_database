"""47 — Restore parenthesized polity names in polities_cliopatria.

Mirrors `enhance_db/src/bin/47_rename_parenthesized_polities.rs`.

Pulls names like "(Han)" from cliopatria_polity_periods and writes them
back into polities_cliopatria where they were stripped.

Usage
-----
    python3 47_rename_parenthesized_polities.py
    python3 47_rename_parenthesized_polities.py --full
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import insert_rows, log, open_db, parse_run_mode


def run(conn: sqlite3.Connection) -> int:
    log("[DB] 47: Renaming polities to match parenthesized names...")
    rows = conn.execute(
        """
        SELECT DISTINCT cpp.polity_id, cpp.polity_name, pc.name
        FROM cliopatria_polity_periods cpp
        JOIN polities_cliopatria pc ON cpp.polity_id = pc.id
        WHERE SUBSTR(cpp.polity_name, 1, 1) = '('
          AND SUBSTR(cpp.polity_name, LENGTH(cpp.polity_name), 1) = ')'
          AND LENGTH(cpp.polity_name) > 2
          AND INSTR(SUBSTR(cpp.polity_name, 2, LENGTH(cpp.polity_name) - 2), '(') = 0
          AND pc.name != cpp.polity_name
        ORDER BY pc.name
        """
    ).fetchall()
    log(f"[DB] {len(rows)} polities to rename")
    for pid, new_name, old_name in rows:
        log(f"  '{old_name}' -> '{new_name}'")

    conn.executemany(
        "UPDATE polities_cliopatria SET name = ? WHERE id = ?",
        [(new_name, pid) for pid, new_name, _ in rows],
    )
    conn.commit()
    return len(rows)


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
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
                {"polity_id": 1, "polity_name": "(Han)"},
                {"polity_id": 2, "polity_name": "Rome"},
            ])
        with open_db(db) as conn:
            run(conn)
            for r in conn.execute("SELECT id, name FROM polities_cliopatria").fetchall():
                log(f"  {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
