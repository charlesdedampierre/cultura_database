"""Helper — focused repair: rebuild identifiers, restore sitelinks_backup, indexes.

Mirrors `enhance_db/src/bin/repair_db.rs`.

Usage
-----
    python3 helper_repair_db.py
    python3 helper_repair_db.py --full
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import insert_rows, log, open_db, parse_run_mode, table_exists


def run(conn: sqlite3.Connection) -> None:
    log("[helper] repair_db: starting...")

    # Phase 1: sitelinks
    if table_exists(conn, "sitelinks_backup"):
        sl = conn.execute("SELECT COUNT(*) FROM sitelinks").fetchone()[0]
        bk = conn.execute("SELECT COUNT(*) FROM sitelinks_backup").fetchone()[0]
        log(f"  sitelinks: {sl}, sitelinks_backup: {bk}")
        if bk > sl:
            conn.execute("DROP TABLE IF EXISTS sitelinks")
            conn.execute("ALTER TABLE sitelinks_backup RENAME TO sitelinks")
            log("  restored sitelinks from backup")
        else:
            conn.execute("DROP TABLE sitelinks_backup")
            log("  dropped stale sitelinks_backup")

    if table_exists(conn, "individuals_backup"):
        conn.execute("DROP TABLE individuals_backup")
        log("  dropped individuals_backup")

    # Phase 2: identifiers
    try:
        n = conn.execute("SELECT COUNT(*) FROM identifiers").fetchone()[0]
        log(f"  identifiers OK: {n} rows")
    except sqlite3.Error:
        log("  identifiers corrupted, rebuilding...")
        conn.execute("DROP TABLE IF EXISTS identifiers_new")
        conn.execute(
            """
            CREATE TABLE identifiers_new (
                wikidata_id TEXT,
                individual_name TEXT,
                property_id TEXT,
                identifier_name TEXT,
                value TEXT,
                url TEXT,
                PRIMARY KEY (wikidata_id, property_id, value)
            )
            """
        )
        try:
            conn.execute(
                "INSERT OR IGNORE INTO identifiers_new "
                "SELECT wikidata_id, individual_name, property_id, "
                "identifier_name, value, url FROM identifiers"
            )
        except sqlite3.Error as e:
            log(f"  copy failed: {e}")
        conn.execute("DROP TABLE identifiers")
        conn.execute("ALTER TABLE identifiers_new RENAME TO identifiers")

    for sql in (
        "CREATE INDEX IF NOT EXISTS idx_identifiers_wikidata ON identifiers(wikidata_id)",
        "CREATE INDEX IF NOT EXISTS idx_identifiers_property ON identifiers(property_id)",
        "CREATE INDEX IF NOT EXISTS idx_identifiers_name ON identifiers(individual_name)",
    ):
        try:
            conn.execute(sql)
        except sqlite3.Error as e:
            log(f"  index error: {e}")

    # Phase 3: individuals indexes
    for sql in (
        "CREATE INDEX IF NOT EXISTS idx_name_en ON individuals(name_en)",
        "CREATE INDEX IF NOT EXISTS idx_birthcity_en ON individuals(birthcity_en)",
    ):
        try:
            conn.execute(sql)
        except sqlite3.Error as e:
            log(f"  index error: {e}")
    conn.commit()
    log("  done")


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, "
                "name_en TEXT, birthcity_en TEXT)"
            )
            insert_rows(seed, "individuals", [
                {"wikidata_id": "Q1", "name_en": "Alice", "birthcity_en": "Paris"},
            ])
            seed.execute(
                "CREATE TABLE identifiers (wikidata_id TEXT, individual_name TEXT, "
                "property_id TEXT, identifier_name TEXT, value TEXT, url TEXT, "
                "PRIMARY KEY (wikidata_id, property_id, value))"
            )
            insert_rows(seed, "identifiers", [
                {"wikidata_id": "Q1", "individual_name": "Alice",
                 "property_id": "P213", "identifier_name": "ORCID",
                 "value": "0000-0001", "url": None},
            ])
            seed.execute("CREATE TABLE sitelinks (id INTEGER)")
            insert_rows(seed, "sitelinks", [{"id": 1}])
        with open_db(db) as conn:
            run(conn)


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
