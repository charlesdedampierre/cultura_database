"""15 - Reorder sitelinks columns: id, wikidata_id, individual_name, ...

Mirrors `enhance_db/src/bin/15_reorder_sitelinks.rs`.

  Inputs : sitelinks (any earlier column order)
  Output : sitelinks rebuilt with column order
             id, wikidata_id, individual_name, site, title, url
           and idx_sitelinks_wikidata recreated.

Usage
-----
    python3 15_reorder_sitelinks.py
    python3 15_reorder_sitelinks.py --full
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import insert_rows, log, open_db, parse_run_mode


def run(conn: sqlite3.Connection) -> None:
    log("=== Step 15: Reorder sitelinks columns ===")

    total = conn.execute("SELECT COUNT(*) FROM sitelinks").fetchone()[0]
    log(f"[15] Sitelinks table has {total} rows")
    cols_before = [r[1] for r in conn.execute("PRAGMA table_info(sitelinks)").fetchall()]
    log(f"[15] Current columns: {', '.join(cols_before)}")

    log("[15] Restructuring sitelinks (moving individual_name after wikidata_id)...")
    conn.executescript(
        """
        DROP TABLE IF EXISTS sitelinks_backup;
        ALTER TABLE sitelinks RENAME TO sitelinks_backup;

        CREATE TABLE sitelinks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wikidata_id TEXT NOT NULL,
            individual_name TEXT,
            site TEXT,
            title TEXT,
            url TEXT
        );

        INSERT INTO sitelinks (id, wikidata_id, individual_name, site, title, url)
        SELECT id, wikidata_id, individual_name, site, title, url
        FROM sitelinks_backup;

        DROP TABLE sitelinks_backup;
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sitelinks_wikidata ON sitelinks(wikidata_id)"
    )
    conn.commit()

    verify = conn.execute("SELECT COUNT(*) FROM sitelinks").fetchone()[0]
    log(f"[15] Sitelinks after restructure: {verify} rows")
    cols_after = [r[1] for r in conn.execute("PRAGMA table_info(sitelinks)").fetchall()]
    log(f"[15] New columns: {', '.join(cols_after)}")
    log("=== Step 15 complete ===")


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db_path) as seed:
            seed.execute(
                "CREATE TABLE sitelinks ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "site TEXT, title TEXT, url TEXT, "
                "wikidata_id TEXT NOT NULL, individual_name TEXT)"
            )
            insert_rows(seed, "sitelinks", [
                {"id": 1, "site": "enwiki", "title": "Alice",
                 "url": "https://en.wikipedia.org/wiki/Alice",
                 "wikidata_id": "Q1", "individual_name": "Alice"},
                {"id": 2, "site": "frwiki", "title": "Bob",
                 "url": "https://fr.wikipedia.org/wiki/Bob",
                 "wikidata_id": "Q2", "individual_name": "Bob"},
            ])
            seed.commit()

        with open_db(db_path) as conn:
            run(conn)
            rows = conn.execute(
                "SELECT id, wikidata_id, individual_name, site, title, url FROM sitelinks"
            ).fetchall()
        for r in rows:
            log(f"  sitelinks: {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
