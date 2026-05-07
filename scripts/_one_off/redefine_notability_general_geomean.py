"""Redefine `individuals.notability_general` as the geometric mean of the
western and non-western indices.

  notability_general := sqrt(notability_western * notability_non_western)

Rationale: an equal-weight geometric mean rewards individuals whose
notability is broad across both western and non-western sources, and
penalises one-sided fame (zero on either side -> zero global score).

The column is dropped and recreated as REAL, then filled in a single
UPDATE pass (the source columns are already present in `individuals`,
so no staging table is needed).
"""

from __future__ import annotations

import math
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "humans_clean.sqlite3"


def now() -> str:
    return time.strftime("%H:%M:%S")


def log(msg: str) -> None:
    print(f"[{now()}] {msg}", flush=True)


def main() -> int:
    if not DB_PATH.exists():
        print(f"database not found: {DB_PATH}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.create_function("sqrt", 1, math.sqrt, deterministic=True)

        cols = {row[1] for row in conn.execute("PRAGMA table_info(individuals)").fetchall()}
        for required in ("notability_western", "notability_non_western"):
            if required not in cols:
                print(f"missing column individuals.{required}", file=sys.stderr)
                return 1

        if "notability_general" in cols:
            log("dropping existing notability_general column ...")
            conn.execute("ALTER TABLE individuals DROP COLUMN notability_general")
            conn.commit()

        log("adding notability_general as REAL ...")
        conn.execute(
            "ALTER TABLE individuals ADD COLUMN notability_general REAL NOT NULL DEFAULT 0"
        )
        conn.commit()

        log("computing geometric mean (sqrt(west * non_west)) for 13M rows ...")
        t0 = time.time()
        cur = conn.execute(
            "UPDATE individuals SET notability_general = "
            "sqrt(CAST(notability_western AS REAL) * CAST(notability_non_western AS REAL))"
        )
        conn.commit()
        log(f"  UPDATE done in {time.time() - t0:.1f}s; rows affected={cur.rowcount:,}")

        log("summary statistics:")
        for col in ("notability_general", "notability_western", "notability_non_western"):
            row = conn.execute(
                f"SELECT MIN({col}), AVG({col}), MAX({col}), "
                f"  SUM(CASE WHEN {col} > 0 THEN 1 ELSE 0 END), COUNT(*) "
                f"FROM individuals"
            ).fetchone()
            print(
                f"  {col}: min={row[0]}, mean={row[1]:.3f}, max={row[2]}, "
                f"non-zero={row[3]:,}/{row[4]:,}"
            )

        log("top 10 by new notability_general:")
        for r in conn.execute(
            "SELECT name_en, notability_general, notability_western, notability_non_western "
            "FROM individuals WHERE name_en IS NOT NULL AND name_en <> '' "
            "ORDER BY notability_general DESC LIMIT 10"
        ):
            print(f"  {r[0]:<35}  gen={r[1]:7.2f}  west={r[2]:>4}  non_west={r[3]:>4}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
