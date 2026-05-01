"""32 - Transfer all tables from source DB to a fresh clean target DB.

Mirrors `enhance_db/src/bin/32_transfer_to_clean_db.rs`.

  Inputs : a corrupted/working SQLite DB (default: data/humans_clean.sqlite3)
  Output : a fresh DB with the same schema and data
           (default: data/humans_clean_new.sqlite3)

Strategy
--------
ATTACH DATABASE 'dst' AS clean, then copy each table via
INSERT INTO clean.<t> SELECT * FROM main.<t>. Skips sqlite internal tables.

Usage
-----
    python3 32_transfer_to_clean_db.py            # synthetic DB
    python3 32_transfer_to_clean_db.py --full     # uses default paths
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

from common import DB_PATH, insert_rows, log, parse_run_mode


def run(src_path: Path | str, dst_path: Path | str) -> dict[str, int]:
    src_path = str(src_path)
    dst_path = str(dst_path)
    log(f"[DB] 32: transfer {src_path} -> {dst_path}")

    if os.path.exists(dst_path):
        os.remove(dst_path)

    conn = sqlite3.connect(src_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(f"ATTACH DATABASE '{dst_path}' AS clean")
    conn.execute("PRAGMA clean.journal_mode=WAL")
    conn.execute("PRAGMA clean.synchronous=OFF")

    objects = conn.execute(
        "SELECT type, name, sql FROM main.sqlite_master "
        "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' "
        "ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END, name"
    ).fetchall()
    tables = [o for o in objects if o[0] == "table"]
    indexes = [o for o in objects if o[0] == "index"]
    log(f"[32] Found {len(tables)} tables and {len(indexes)} indexes")

    counts: dict[str, int] = {}
    for _, name, sql in tables:
        clean_sql = sql.replace("CREATE TABLE ", "CREATE TABLE clean.", 1)
        clean_sql = clean_sql.replace("CREATE TABLE clean.clean.", "CREATE TABLE clean.")
        conn.execute(clean_sql)
        cur = conn.execute(f'INSERT INTO clean."{name}" SELECT * FROM main."{name}"')
        counts[name] = cur.rowcount
        log(f"[32]   {name}: {cur.rowcount} rows copied")

    for _, name, sql in indexes:
        clean_sql = (
            sql.replace("CREATE INDEX ", "CREATE INDEX clean.")
               .replace("CREATE UNIQUE INDEX ", "CREATE UNIQUE INDEX clean.")
        )
        clean_sql = clean_sql.replace("clean.clean.", "clean.")
        try:
            conn.execute(clean_sql)
        except sqlite3.Error as e:
            log(f"[32]   index {name} FAILED: {e}")

    conn.commit()

    for _, name, _ in tables:
        s = conn.execute(f'SELECT COUNT(*) FROM main."{name}"').fetchone()[0]
        d = conn.execute(f'SELECT COUNT(*) FROM clean."{name}"').fetchone()[0]
        status = "OK" if s == d else "MISMATCH"
        log(f"[32]   verify {name}: src={s} dst={d} [{status}]")

    conn.execute("DETACH DATABASE clean")
    conn.close()

    new_conn = sqlite3.connect(dst_path)
    integrity = new_conn.execute("PRAGMA integrity_check").fetchone()[0]
    new_conn.close()
    log(f"[32] integrity: {integrity}")
    return counts


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src.sqlite3"
        dst = Path(tmp) / "dst.sqlite3"
        with sqlite3.connect(src) as seed:
            seed.execute("CREATE TABLE foo (id INTEGER PRIMARY KEY, label TEXT)")
            seed.execute("CREATE TABLE bar (k TEXT, v INTEGER)")
            seed.execute("CREATE INDEX idx_foo_label ON foo(label)")
            insert_rows(seed, "foo", [{"id": 1, "label": "alpha"}, {"id": 2, "label": "beta"}])
            insert_rows(seed, "bar", [{"k": "x", "v": 10}, {"k": "y", "v": 20}, {"k": "z", "v": 30}])

        counts = run(src, dst)
        with sqlite3.connect(dst) as check:
            foo_rows = check.execute("SELECT * FROM foo").fetchall()
            bar_rows = check.execute("SELECT * FROM bar").fetchall()
        log(f"[sample] copied counts={counts}")
        log(f"  foo: {foo_rows}")
        log(f"  bar: {bar_rows}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        run(DB_PATH, DB_PATH.parent / "humans_clean_new.sqlite3")
    else:
        _sample_main()
