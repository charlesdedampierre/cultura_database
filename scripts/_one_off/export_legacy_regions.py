"""One-off: export the soon-to-be-dropped tables to data/legacy_regions/*.csv.

Tables exported (then dropped from humans_clean.sqlite3 in the next step):
    regions, individuals_regions, individuals_countries, modern_country

Estimated runtime: ~2-3 minutes (12M rows total, dominated by
individuals_countries + individuals_regions).
"""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB = PROJECT_ROOT / "data" / "humans_clean.sqlite3"
OUT = PROJECT_ROOT / "data" / "legacy_regions"

TABLES = ["regions", "individuals_regions", "individuals_countries", "modern_country"]


def export_table(conn: sqlite3.Connection, table: str, out_path: Path) -> int:
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    cur = conn.execute(f"SELECT {', '.join(cols)} FROM {table}")
    n = 0
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for row in tqdm(cur, total=total, desc=table, unit="row"):
            w.writerow(row)
            n += 1
    return n


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        for t in TABLES:
            out = OUT / f"{t}.csv"
            n = export_table(conn, t, out)
            size_mb = out.stat().st_size / (1024 * 1024)
            print(f"[export] {t}: {n:,} rows -> {out.name} ({size_mb:.1f} MB)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
