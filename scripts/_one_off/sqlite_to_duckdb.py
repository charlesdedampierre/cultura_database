"""Copy data/humans_clean.sqlite3 into a DuckDB database.

Excluded tables  : identifiers, works, wikimedia_links
All columns kept (including wikidata_id and wikipedia URL columns).
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import duckdb
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "humans_clean.sqlite3"
DST = ROOT / "data" / "humans_clean.duckdb"

SKIP_TABLES = {"identifiers", "works", "wikimedia_links"}
SKIP_COLUMNS: set[str] = set()


def list_tables(sqlite_path: Path) -> list[tuple[str, list[str], int]]:
    con = sqlite3.connect(str(sqlite_path))
    cur = con.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    names = [r[0] for r in cur.fetchall()]
    out: list[tuple[str, list[str], int]] = []
    for n in names:
        if n in SKIP_TABLES:
            continue
        cur.execute(f'PRAGMA table_info("{n}")')
        cols = [r[1] for r in cur.fetchall() if r[1] not in SKIP_COLUMNS]
        cur.execute(f'SELECT COUNT(*) FROM "{n}"')
        out.append((n, cols, cur.fetchone()[0]))
    con.close()
    return out


def main() -> int:
    if not SRC.exists():
        print(f"Source not found: {SRC}", file=sys.stderr)
        return 1
    if DST.exists():
        print(f"Destination already exists: {DST}", file=sys.stderr)
        return 1

    tables = list_tables(SRC)
    total_rows = sum(n for _, _, n in tables)
    print(f"Source : {SRC} ({SRC.stat().st_size / 1e9:.1f} GB)")
    print(f"Target : {DST}")
    print(f"Tables : {len(tables)} (skipped: {sorted(SKIP_TABLES)})")
    print(f"Total rows: {total_rows:,}")

    con = duckdb.connect(str(DST))
    con.execute("INSTALL sqlite")
    con.execute("LOAD sqlite")
    con.execute(f"ATTACH '{SRC}' AS src (TYPE SQLITE, READ_ONLY)")

    t0 = time.time()
    bar = tqdm(tables, unit="table")
    for name, cols, n_rows in bar:
        bar.set_description(f"{name} ({n_rows:,} rows, {len(cols)} cols)")
        col_list = ", ".join(f'"{c}"' for c in cols)
        t_start = time.time()
        con.execute(
            f'CREATE TABLE main."{name}" AS SELECT {col_list} FROM src."{name}"'
        )
        dt = time.time() - t_start
        rate = n_rows / dt if dt > 0 else 0
        bar.write(f"  {name}: {n_rows:,} rows in {dt:.1f}s ({rate:,.0f} rows/s)")

    con.execute("DETACH src")
    con.close()

    dt_total = time.time() - t0
    size_gb = DST.stat().st_size / 1e9
    print(f"\nDone in {dt_total/60:.1f} min. DuckDB size: {size_gb:.1f} GB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
