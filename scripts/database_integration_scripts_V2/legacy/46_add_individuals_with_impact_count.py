"""46 — Add `individuals_with_impact_count` to polities_cliopatria.

Mirrors `enhance_db/src/bin/46_add_individuals_with_impact_count.rs`.

  Inputs : individuals_cliopatria (polity_id, impact_date)
  Output : polities_cliopatria.individuals_with_impact_count populated.

Usage
-----
    python3 46_add_individuals_with_impact_count.py
    python3 46_add_individuals_with_impact_count.py --full
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import (
    DB_PATH,
    add_column_if_missing,
    insert_rows,
    log,
    open_db,
    parse_run_mode,
)


def run(conn: sqlite3.Connection) -> int:
    log("[DB] 46: Add individuals_with_impact_count to polities_cliopatria...")

    add_column_if_missing(
        conn, "polities_cliopatria", "individuals_with_impact_count",
        "INTEGER DEFAULT 0",
    )

    counts = dict(
        conn.execute(
            "SELECT polity_id, COUNT(*) FROM individuals_cliopatria "
            "WHERE impact_date IS NOT NULL GROUP BY polity_id"
        ).fetchall()
    )
    log(f"[DB] {len(counts)} polities have individuals with impact dates.")

    conn.execute("UPDATE polities_cliopatria SET individuals_with_impact_count = 0")
    conn.executemany(
        "UPDATE polities_cliopatria SET individuals_with_impact_count = ? WHERE id = ?",
        [(c, pid) for pid, c in counts.items()],
    )
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM polities_cliopatria").fetchone()[0]
    with_imp = conn.execute(
        "SELECT COUNT(*) FROM polities_cliopatria WHERE individuals_with_impact_count > 0"
    ).fetchone()[0]
    log(f"[DB] polities total={total} with_impact={with_imp}")

    return len(counts)


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE polities_cliopatria (id INTEGER PRIMARY KEY, "
                "name TEXT, individuals_count INTEGER DEFAULT 0)"
            )
            insert_rows(seed, "polities_cliopatria", [
                {"id": 1, "name": "Han", "individuals_count": 5},
                {"id": 2, "name": "Rome", "individuals_count": 7},
                {"id": 3, "name": "Maya", "individuals_count": 0},
            ])
            seed.execute(
                "CREATE TABLE individuals_cliopatria (wikidata_id TEXT, "
                "polity_id INTEGER, impact_date INTEGER)"
            )
            insert_rows(seed, "individuals_cliopatria", [
                {"wikidata_id": "Q1", "polity_id": 1, "impact_date": 100},
                {"wikidata_id": "Q2", "polity_id": 1, "impact_date": None},
                {"wikidata_id": "Q3", "polity_id": 2, "impact_date": 50},
                {"wikidata_id": "Q4", "polity_id": 2, "impact_date": 75},
            ])

        with open_db(db) as conn:
            run(conn)
            for r in conn.execute(
                "SELECT id, name, individuals_with_impact_count "
                "FROM polities_cliopatria ORDER BY id"
            ).fetchall():
                log(f"  {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
