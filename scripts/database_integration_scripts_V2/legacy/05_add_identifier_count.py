"""05 - Add `identifiers_count` to individuals.

Mirrors `enhance_db/src/bin/05_add_identifier_count.rs`.

  Inputs : individuals, identifiers
  Output : individuals.identifiers_count populated as the per-row count
           of matching `identifiers.wikidata_id`.

Usage
-----
    python3 05_add_identifier_count.py
    python3 05_add_identifier_count.py --full
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import (
    add_column_if_missing,
    insert_rows,
    log,
    open_db,
    parse_run_mode,
)


def run(conn: sqlite3.Connection) -> None:
    log("[DB] 05: Adding identifiers_count to individuals...")
    if add_column_if_missing(conn, "individuals", "identifiers_count", "INTEGER DEFAULT 0"):
        log("[DB] Added identifiers_count column")

    log("[DB] Computing identifier counts...")
    conn.execute(
        """
        UPDATE individuals SET identifiers_count = (
            SELECT COUNT(*) FROM identifiers
            WHERE identifiers.wikidata_id = individuals.wikidata_id
        )
        """
    )
    conn.commit()

    total = conn.execute(
        "SELECT COUNT(*) FROM individuals WHERE identifiers_count > 0"
    ).fetchone()[0]
    max_count = conn.execute(
        "SELECT MAX(identifiers_count) FROM individuals"
    ).fetchone()[0] or 0
    avg_row = conn.execute(
        "SELECT AVG(identifiers_count) FROM individuals WHERE identifiers_count > 0"
    ).fetchone()
    avg = avg_row[0] if avg_row and avg_row[0] is not None else 0.0

    log(f"[DB] Individuals with identifiers: {total}")
    log(f"[DB] Max identifiers per individual: {max_count}")
    log(f"[DB] Avg identifiers (for those with any): {avg:.1f}")
    log("[DB] 05: Done.")


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db_path) as seed:
            seed.execute("CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, name_en TEXT)")
            seed.execute(
                "CREATE TABLE identifiers ("
                "wikidata_id TEXT, property_id TEXT, value TEXT)"
            )
            insert_rows(seed, "individuals", [
                {"wikidata_id": "Q1", "name_en": "Alice"},
                {"wikidata_id": "Q2", "name_en": "Bob"},
                {"wikidata_id": "Q3", "name_en": "Cleo"},
            ])
            insert_rows(seed, "identifiers", [
                {"wikidata_id": "Q1", "property_id": "P213", "value": "x"},
                {"wikidata_id": "Q1", "property_id": "P214", "value": "y"},
                {"wikidata_id": "Q1", "property_id": "P227", "value": "z"},
                {"wikidata_id": "Q2", "property_id": "P213", "value": "a"},
            ])
            seed.commit()

        with open_db(db_path) as conn:
            run(conn)
            rows = conn.execute(
                "SELECT wikidata_id, name_en, identifiers_count FROM individuals "
                "ORDER BY wikidata_id"
            ).fetchall()
        for r in rows:
            log(f"  individuals: {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
