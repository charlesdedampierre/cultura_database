"""Mirror humans_clean.sqlite3 into a fresh humans_clean.duckdb (all tables).

Strategy:
  - ATTACH the sqlite source via the sqlite_scanner extension.
  - Per table: stream rows into a DuckDB table with `CREATE TABLE ... AS SELECT *`.
  - Show progress with tqdm.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import duckdb
from tqdm import tqdm

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "data" / "humans_clean.sqlite3"
DST = REPO / "data" / "humans_clean.duckdb"


def main():
    if not SRC.exists():
        sys.exit(f"missing source: {SRC}")
    if DST.exists():
        sys.exit(f"refusing to overwrite existing {DST}")

    print(f"src: {SRC} ({SRC.stat().st_size / 1e9:.2f} GB)")
    print(f"dst: {DST}")

    con = duckdb.connect(str(DST))
    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute(f"ATTACH '{SRC}' AS src (TYPE SQLITE, READ_ONLY);")

    # Pull table list from the attached sqlite via DuckDB's information_schema.
    rows = con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_catalog = 'src' AND table_schema = 'main' "
        "  AND table_name NOT LIKE 'sqlite_%' "
        "ORDER BY table_name"
    ).fetchall()
    tables = [r[0] for r in rows]
    print(f"copying {len(tables)} tables: {tables}")

    t0 = time.perf_counter()
    pbar = tqdm(tables, unit="table")
    for name in pbar:
        pbar.set_postfix_str(name)
        # Quote identifier with double quotes to be safe.
        q = f'"{name}"'
        ts = time.perf_counter()
        con.execute(f"CREATE TABLE {q} AS SELECT * FROM src.{q};")
        n = con.execute(f"SELECT COUNT(*) FROM {q}").fetchone()[0]
        pbar.write(f"  {name:38s} {n:>12,} rows  ({time.perf_counter()-ts:6.1f}s)")

    con.execute("DETACH src;")
    con.close()

    sz = DST.stat().st_size
    print(f"\ndone in {time.perf_counter() - t0:.1f}s — {DST.name} = {sz/1e9:.2f} GB")


if __name__ == "__main__":
    main()
