"""61 — Rebuild identifiers from the merged TSV (streaming).

Mirrors `enhance_db/src/bin/61_rebuild_identifiers_v2.rs`.

  Inputs : data/all_humans/all_human_identifiers_v2.tsv
              (header + columns: wikidata_id <TAB> property_id <TAB> value)
  Output : identifiers (wikidata_id, property_id, value PK)
           individuals.identifiers_count refreshed
           identifier_types.count refreshed (if column exists)

The Rust version sent an email at the end. Credentials are not embedded
here — see global instructions for how to send notifications instead.

Usage
-----
    python3 61_rebuild_identifiers_v2.py
    python3 61_rebuild_identifiers_v2.py --full
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from tqdm import tqdm

from common import (
    ALL_HUMANS_DIR,
    column_exists,
    insert_rows,
    log,
    open_db,
    parse_run_mode,
)

TSV_PATH = ALL_HUMANS_DIR / "all_human_identifiers_v2.tsv"
BATCH = 100_000


def run(conn: sqlite3.Connection, tsv_path: Path = TSV_PATH) -> int:
    log("[DB] 61: rebuild identifiers from TSV (streaming)...")
    conn.execute("DROP TABLE IF EXISTS identifiers")
    conn.execute(
        """
        CREATE TABLE identifiers (
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

    cur = conn.cursor()
    cur.execute("BEGIN")
    buf: list[tuple[str, str, str]] = []
    total = 0
    with open(tsv_path, "r", encoding="utf-8") as fh:
        header = fh.readline()  # skip header
        del header
        for line in tqdm(fh, desc="61", unit="line"):
            parts = line.rstrip("\n").split("\t", 2)
            if len(parts) < 3:
                continue
            qid, pid, value = parts
            if not qid.startswith("Q") or not pid.startswith("P"):
                continue
            buf.append((qid, pid, value))
            if len(buf) >= BATCH:
                cur.executemany(
                    "INSERT OR IGNORE INTO identifiers "
                    "(wikidata_id, property_id, value) VALUES (?,?,?)",
                    buf,
                )
                total += len(buf)
                buf.clear()
                conn.commit()
                cur.execute("BEGIN")
    if buf:
        cur.executemany(
            "INSERT OR IGNORE INTO identifiers "
            "(wikidata_id, property_id, value) VALUES (?,?,?)",
            buf,
        )
        total += len(buf)
    conn.commit()
    log(f"[DB] inserted {total} identifier rows")

    for sql in (
        "CREATE INDEX IF NOT EXISTS idx_identifiers_wikidata ON identifiers(wikidata_id)",
        "CREATE INDEX IF NOT EXISTS idx_identifiers_property ON identifiers(property_id)",
        "CREATE INDEX IF NOT EXISTS idx_identifiers_name ON identifiers(individual_name)",
    ):
        conn.execute(sql)

    conn.execute(
        """
        UPDATE individuals SET identifiers_count = (
            SELECT COUNT(*) FROM identifiers
            WHERE identifiers.wikidata_id = individuals.wikidata_id
        )
        """
    )
    if column_exists(conn, "identifier_types", "count"):
        conn.execute(
            """
            UPDATE identifier_types SET count = (
                SELECT COUNT(*) FROM identifiers
                WHERE identifiers.property_id = identifier_types.property_id
            )
            """
        )
    conn.commit()
    # TODO: send notification (Gmail SMTP / app password — see global instructions).
    return total


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tsv = Path(tmp) / "ids.tsv"
        tsv.write_text(
            "wikidata_id\tproperty_id\tvalue\n"
            "Q1\tP213\t0000-0001-1\n"
            "Q1\tP214\t12345\n"
            "Q2\tP213\t0000-0002-2\n"
            "Q3\tnotapid\tx\n"
        )
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, "
                "identifiers_count INTEGER DEFAULT 0)"
            )
            insert_rows(seed, "individuals", [
                {"wikidata_id": "Q1", "identifiers_count": 0},
                {"wikidata_id": "Q2", "identifiers_count": 0},
            ])
            seed.execute(
                "CREATE TABLE identifier_types (property_id TEXT, count INTEGER)"
            )
            insert_rows(seed, "identifier_types", [
                {"property_id": "P213", "count": 0},
                {"property_id": "P214", "count": 0},
            ])
        with open_db(db) as conn:
            run(conn, tsv_path=tsv)
            for r in conn.execute(
                "SELECT wikidata_id, property_id, value FROM identifiers"
            ):
                log(f"  {r}")
            for r in conn.execute(
                "SELECT wikidata_id, identifiers_count FROM individuals"
            ):
                log(f"  ind {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
