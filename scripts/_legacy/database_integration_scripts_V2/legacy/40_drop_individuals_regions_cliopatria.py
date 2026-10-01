"""40 - Drop the redundant individuals_regions_cliopatria table.

Mirrors `enhance_db/src/bin/40_drop_individuals_regions_cliopatria.rs`.

  Inputs : individuals_regions_cliopatria (built by 35/36; redundant once
           individuals_cliopatria exists from step 39)
  Output : table dropped, VACUUM run.

Usage
-----
    python3 40_drop_individuals_regions_cliopatria.py            # synthetic
    python3 40_drop_individuals_regions_cliopatria.py --full     # real DB
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import insert_rows, log, open_db, parse_run_mode


def run(conn: sqlite3.Connection, *, vacuum: bool = True) -> bool:
    log("[DB] 40: Dropping individuals_regions_cliopatria...")
    conn.execute("DROP TABLE IF EXISTS individuals_regions_cliopatria")
    conn.commit()
    if vacuum:
        # VACUUM cannot run inside a transaction
        conn.isolation_level = None
        conn.execute("VACUUM")
        conn.isolation_level = ""
        log("[40] VACUUM done")
    return True


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE individuals_regions_cliopatria (wikidata_id TEXT PRIMARY KEY, name_en TEXT)"
            )
            insert_rows(seed, "individuals_regions_cliopatria", [
                {"wikidata_id": "Q1", "name_en": "A"},
                {"wikidata_id": "Q2", "name_en": "B"},
            ])
        with open_db(db) as conn:
            run(conn, vacuum=False)  # skip VACUUM in WAL+open_db sample path
            existing = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='individuals_regions_cliopatria'"
            ).fetchone()
        log(f"[sample] table after drop: {existing}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
