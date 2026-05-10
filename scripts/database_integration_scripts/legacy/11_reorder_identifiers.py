"""11 - Reorder identifiers columns and re-establish PK + indexes.

Mirrors `enhance_db/src/bin/11_reorder_identifiers.rs`.

  Inputs : identifiers (any earlier shape)
  Output : identifiers rebuilt with column order
             wikidata_id, individual_name, property_id,
             identifier_name, value, url
           PK (wikidata_id, property_id, value) + 3 indexes.

Usage
-----
    python3 11_reorder_identifiers.py
    python3 11_reorder_identifiers.py --full
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import insert_rows, log, open_db, parse_run_mode


def run(conn: sqlite3.Connection) -> None:
    log("=== Step 11: Reorder identifiers columns ===")

    total = conn.execute("SELECT COUNT(*) FROM identifiers").fetchone()[0]
    log(f"[11] Identifiers table has {total} rows")

    log("[11] Restructuring identifiers (reordering columns)...")
    conn.executescript(
        """
        DROP TABLE IF EXISTS identifiers_backup;
        ALTER TABLE identifiers RENAME TO identifiers_backup;

        CREATE TABLE identifiers (
            wikidata_id TEXT,
            individual_name TEXT,
            property_id TEXT,
            identifier_name TEXT,
            value TEXT,
            url TEXT,
            PRIMARY KEY (wikidata_id, property_id, value)
        );

        INSERT INTO identifiers (wikidata_id, individual_name, property_id, identifier_name, value, url)
        SELECT wikidata_id, individual_name, property_id, identifier_name, value, url
        FROM identifiers_backup;

        DROP TABLE identifiers_backup;
        """
    )
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_identifiers_wikidata ON identifiers(wikidata_id);
        CREATE INDEX IF NOT EXISTS idx_identifiers_property ON identifiers(property_id);
        CREATE INDEX IF NOT EXISTS idx_identifiers_name ON identifiers(individual_name);
        """
    )
    conn.commit()

    verify = conn.execute("SELECT COUNT(*) FROM identifiers").fetchone()[0]
    log(f"[11] Identifiers after restructure: {verify} rows")

    cols = [r[1] for r in conn.execute("PRAGMA table_info(identifiers)").fetchall()]
    log(f"[11] Column order: {', '.join(cols)}")
    log("=== Step 11 complete ===")


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db_path) as seed:
            # Seed in messy column order
            seed.execute(
                "CREATE TABLE identifiers ("
                "value TEXT, identifier_name TEXT, wikidata_id TEXT, "
                "url TEXT, individual_name TEXT, property_id TEXT)"
            )
            insert_rows(seed, "identifiers", [
                {"value": "0000-0001", "identifier_name": "ISNI", "wikidata_id": "Q1",
                 "url": "https://isni.org/0000-0001", "individual_name": "Alice", "property_id": "P213"},
                {"value": "12345", "identifier_name": "VIAF", "wikidata_id": "Q2",
                 "url": "https://viaf.org/12345", "individual_name": "Bob", "property_id": "P214"},
            ])
            seed.commit()

        with open_db(db_path) as conn:
            run(conn)
            rows = conn.execute(
                "SELECT wikidata_id, individual_name, property_id, identifier_name, value, url "
                "FROM identifiers"
            ).fetchall()
        for r in rows:
            log(f"  identifiers: {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
