"""Mirror a SQLite cultura DB into a fresh DuckDB (all tables, no consolidation).

Default: `data/humans_clean.sqlite3` -> `data/humans_clean.duckdb`.
Use `--src` / `--dst` to point at the v2 sample build for a from-scratch
end-to-end check (`humans_v2.sqlite3` or `humans_v2.sample.sqlite3`).

Strategy: ATTACH the sqlite source via duckdb's sqlite_scanner, then
`CREATE TABLE ... AS SELECT *` per table with a tqdm progress bar.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import duckdb
from tqdm import tqdm

REPO = Path(__file__).resolve().parents[1]
DEFAULT_SRC = REPO / "data" / "humans_clean.sqlite3"
DEFAULT_DST = REPO / "data" / "humans_clean.duckdb"


def mirror(src: Path, dst: Path) -> None:
    if not src.exists():
        sys.exit(f"missing source: {src}")
    if dst.exists():
        sys.exit(f"refusing to overwrite existing {dst}")

    print(f"src: {src} ({src.stat().st_size / 1e9:.2f} GB)")
    print(f"dst: {dst}")

    con = duckdb.connect(str(dst))
    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute(f"ATTACH '{src}' AS src (TYPE SQLITE, READ_ONLY);")

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
        q = f'"{name}"'
        ts = time.perf_counter()
        con.execute(f"CREATE TABLE {q} AS SELECT * FROM src.{q};")
        n = con.execute(f"SELECT COUNT(*) FROM {q}").fetchone()[0]
        pbar.write(f"  {name:38s} {n:>12,} rows  ({time.perf_counter()-ts:6.1f}s)")

    con.execute("DETACH src;")
    con.close()

    sz = dst.stat().st_size
    print(f"\ndone in {time.perf_counter() - t0:.1f}s — {dst.name} = {sz/1e9:.2f} GB")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--src", default=str(DEFAULT_SRC),
                   help=f"source SQLite (default: {DEFAULT_SRC})")
    p.add_argument("--dst", default=str(DEFAULT_DST),
                   help=f"destination DuckDB (default: {DEFAULT_DST})")
    args = p.parse_args()
    mirror(Path(args.src), Path(args.dst))


if __name__ == "__main__":
    main()
