"""37 - Drop count column on individuals_regions_cliopatria, then create
polities_cliopatria with all polities and individuals_count.

Mirrors `enhance_db/src/bin/37_create_polities_cliopatria.rs`.

  Inputs : individuals_regions_cliopatria, cliopatria.db / polities
  Output : polities_cliopatria (id PK, name, type, wikipedia_url,
           wikidata_id, individuals_count)

Usage
-----
    python3 37_create_polities_cliopatria.py            # synthetic
    python3 37_create_polities_cliopatria.py --full     # real DB
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import (
    PROJECT_ROOT,
    column_exists,
    insert_rows,
    log,
    open_db,
    parse_run_mode,
)

CLIO_DB_PATH = PROJECT_ROOT / "cliopatria_data" / "processing" / "data" / "cliopatria.db"


def _strip_parens(name: str) -> str:
    s = name.strip()
    if s.startswith("(") and s.endswith(")"):
        return s[1:-1]
    return s


def run(conn: sqlite3.Connection, clio_db_path: Path | str = CLIO_DB_PATH) -> int:
    log("[DB] 37: Creating polities_cliopatria...")

    if column_exists(conn, "individuals_regions_cliopatria", "count"):
        conn.execute("ALTER TABLE individuals_regions_cliopatria DROP COLUMN count")
        log("[37] dropped count column")

    polities: list[tuple] = []
    with sqlite3.connect(str(clio_db_path)) as clio:
        for pid, name, ptype, url, qid in clio.execute(
            "SELECT id, name, type, wikipedia_url, wikidata_id FROM polities"
        ):
            polities.append((pid, _strip_parens(name), ptype, url, qid))
    log(f"[37] polities loaded: {len(polities)}")

    polity_counts: dict[str, int] = {}
    for p, c in conn.execute(
        "SELECT polity_cliopatria, COUNT(*) FROM individuals_regions_cliopatria "
        "WHERE polity_cliopatria IS NOT NULL GROUP BY polity_cliopatria"
    ):
        polity_counts[p] = c
    log(f"[37] polities with individuals: {len(polity_counts)}")

    conn.execute("DROP TABLE IF EXISTS polities_cliopatria")
    conn.execute(
        """
        CREATE TABLE polities_cliopatria (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT,
            wikipedia_url TEXT,
            wikidata_id TEXT,
            individuals_count INTEGER DEFAULT 0
        )
        """
    )
    rows = [(pid, name, ptype, url, qid, polity_counts.get(name, 0))
            for pid, name, ptype, url, qid in polities]
    conn.executemany(
        "INSERT INTO polities_cliopatria (id, name, type, wikipedia_url, wikidata_id, individuals_count) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pc_name ON polities_cliopatria(name)")
    conn.commit()
    log(f"[37] inserted {len(rows)} polities")
    return len(rows)


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        clio = Path(tmp) / "clio.db"
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(clio) as c:
            c.execute(
                "CREATE TABLE polities (id INTEGER, name TEXT, type TEXT, "
                "wikipedia_url TEXT, wikidata_id TEXT)"
            )
            insert_rows(c, "polities", [
                {"id": 1, "name": "France", "type": "kingdom",
                 "wikipedia_url": "https://en.wikipedia.org/wiki/France", "wikidata_id": "Q142"},
                {"id": 2, "name": "(British Empire)", "type": "empire",
                 "wikipedia_url": "https://en.wikipedia.org/wiki/British_Empire", "wikidata_id": "Q8680"},
            ])
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE individuals_regions_cliopatria (wikidata_id TEXT PRIMARY KEY, "
                "name_en TEXT, url TEXT, origin TEXT, polity_cliopatria TEXT, count INTEGER)"
            )
            insert_rows(seed, "individuals_regions_cliopatria", [
                {"wikidata_id": "Q1", "name_en": "A", "url": None, "origin": "nationality",
                 "polity_cliopatria": "France", "count": 1},
                {"wikidata_id": "Q2", "name_en": "B", "url": None, "origin": "nationality",
                 "polity_cliopatria": "France", "count": 1},
            ])
        with open_db(db) as conn:
            n = run(conn, clio_db_path=clio)
            rows = conn.execute("SELECT * FROM polities_cliopatria").fetchall()
        log(f"[sample] {n} polities: {rows}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
