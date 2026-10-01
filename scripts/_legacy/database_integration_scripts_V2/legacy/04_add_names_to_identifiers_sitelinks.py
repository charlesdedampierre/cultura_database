"""04 - Backfill `individual_name` in identifiers and sitelinks.

Mirrors `enhance_db/src/bin/04_add_names_to_identifiers_sitelinks.rs`.

  Inputs : individuals (wikidata_id, name_en)
           identifiers, sitelinks
  Output : sitelinks.individual_name added (if missing) and populated
           identifiers.individual_name re-populated where blank/null

Usage
-----
    python3 04_add_names_to_identifiers_sitelinks.py
    python3 04_add_names_to_identifiers_sitelinks.py --full
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

BATCH = 1_000_000


def _update_in_batches(conn: sqlite3.Connection, sql: str, batch_size: int, total: int, desc: str) -> None:
    if total <= 0:
        return
    n_batches = (total + batch_size - 1) // batch_size
    try:
        from tqdm import tqdm
        bar = tqdm(total=n_batches, desc=desc, unit="batch")
    except ImportError:
        bar = None
    for _ in range(n_batches):
        conn.execute(sql, (batch_size,))
        conn.commit()
        if bar is not None:
            bar.update(1)
    if bar is not None:
        bar.close()


def run(conn: sqlite3.Connection) -> tuple[int, int]:
    log("[DB] 04: Adding individual names to identifiers and sitelinks...")

    if add_column_if_missing(conn, "sitelinks", "individual_name", "TEXT"):
        log("[DB] Added individual_name column to sitelinks")

    sl_total = conn.execute(
        "SELECT COUNT(*) FROM sitelinks WHERE individual_name IS NULL"
    ).fetchone()[0]
    log(f"[DB] Sitelinks rows to update: {sl_total}")
    _update_in_batches(
        conn,
        """
        UPDATE sitelinks SET individual_name = (
            SELECT individuals.name_en FROM individuals
            WHERE individuals.wikidata_id = sitelinks.wikidata_id
        ) WHERE id IN (
            SELECT id FROM sitelinks WHERE individual_name IS NULL LIMIT ?
        )
        """,
        BATCH,
        sl_total,
        "sitelinks names",
    )

    id_total = conn.execute(
        "SELECT COUNT(*) FROM identifiers WHERE individual_name IS NULL OR individual_name = ''"
    ).fetchone()[0]
    log(f"[DB] Identifiers rows to update: {id_total}")
    _update_in_batches(
        conn,
        """
        UPDATE identifiers SET individual_name = (
            SELECT individuals.name_en FROM individuals
            WHERE individuals.wikidata_id = identifiers.wikidata_id
        ) WHERE rowid IN (
            SELECT rowid FROM identifiers
            WHERE individual_name IS NULL OR individual_name = '' LIMIT ?
        )
        """,
        BATCH,
        id_total,
        "identifier names",
    )

    log("[DB] 04: Done.")
    return sl_total, id_total


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db_path) as seed:
            seed.execute("CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, name_en TEXT)")
            seed.execute(
                "CREATE TABLE identifiers ("
                "wikidata_id TEXT, individual_name TEXT, property_id TEXT, value TEXT)"
            )
            seed.execute(
                "CREATE TABLE sitelinks ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, wikidata_id TEXT, site TEXT, title TEXT)"
            )
            insert_rows(seed, "individuals", [
                {"wikidata_id": "Q1", "name_en": "Alice"},
                {"wikidata_id": "Q2", "name_en": "Bob"},
            ])
            insert_rows(seed, "identifiers", [
                {"wikidata_id": "Q1", "individual_name": None, "property_id": "P213", "value": "0000-0001"},
                {"wikidata_id": "Q2", "individual_name": "", "property_id": "P214", "value": "viaf-1"},
            ])
            insert_rows(seed, "sitelinks", [
                {"wikidata_id": "Q1", "site": "enwiki", "title": "Alice"},
                {"wikidata_id": "Q2", "site": "frwiki", "title": "Bob"},
            ])
            seed.commit()

        with open_db(db_path) as conn:
            run(conn)
            ident = conn.execute("SELECT wikidata_id, individual_name FROM identifiers").fetchall()
            sl = conn.execute("SELECT wikidata_id, individual_name FROM sitelinks").fetchall()

        for r in ident:
            log(f"  identifiers: {r}")
        for r in sl:
            log(f"  sitelinks:   {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
