"""Add pantheon_2_db and cross_verified_db flags to the individuals table.

For each individual (wikidata_id), set the column to 1 when the same
Wikidata QID appears in:
  - data/similar_databases/pantheon 2.0/person_2025_update.csv (column `wd_id`)
  - data/similar_databases/cross-verified-database/cross-verified-database.utf8.csv.gz (column `wikidata_code`)
Otherwise 0.
"""

from __future__ import annotations

import csv
import gzip
import sqlite3
import sys
from pathlib import Path

from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "humans_clean.sqlite3"
PANTHEON_CSV = ROOT / "data" / "similar_databases" / "pantheon 2.0" / "person_2025_update.csv"
CROSS_VERIFIED_GZ = (
    ROOT
    / "data"
    / "similar_databases"
    / "cross-verified-database"
    / "cross-verified-database.utf8.csv.gz"
)

BATCH = 50_000


def load_qids_from_csv(path: Path, qid_column: str, total_hint: int | None = None) -> set[str]:
    qids: set[str] = set()
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in tqdm(reader, total=total_hint, desc=f"reading {path.name}"):
            qid = (row.get(qid_column) or "").strip()
            if qid.startswith("Q"):
                qids.add(qid)
    return qids


def load_qids_from_gz(path: Path, qid_column: str, total_hint: int | None = None) -> set[str]:
    qids: set[str] = set()
    with gzip.open(path, mode="rt", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in tqdm(reader, total=total_hint, desc=f"reading {path.name}"):
            qid = (row.get(qid_column) or "").strip()
            if qid.startswith("Q"):
                qids.add(qid)
    return qids


def ensure_column(conn: sqlite3.Connection, column: str) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(individuals)").fetchall()}
    if column not in cols:
        conn.execute(
            f"ALTER TABLE individuals ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0"
        )
        print(f"added column individuals.{column}")
    else:
        print(f"column individuals.{column} already exists")


def flag_qids(conn: sqlite3.Connection, column: str, qids: set[str]) -> int:
    conn.execute(f"UPDATE individuals SET {column} = 0")
    if not qids:
        return 0
    conn.execute("CREATE TEMP TABLE _qids (wikidata_id TEXT PRIMARY KEY)")
    qid_list = list(qids)
    for i in tqdm(range(0, len(qid_list), BATCH), desc=f"staging {column} qids"):
        chunk = qid_list[i : i + BATCH]
        conn.executemany("INSERT OR IGNORE INTO _qids(wikidata_id) VALUES (?)", ((q,) for q in chunk))
    cur = conn.execute(
        f"UPDATE individuals SET {column} = 1 "
        "WHERE wikidata_id IN (SELECT wikidata_id FROM _qids)"
    )
    updated = cur.rowcount
    conn.execute("DROP TABLE _qids")
    return updated


def main() -> int:
    if not DB_PATH.exists():
        print(f"database not found: {DB_PATH}", file=sys.stderr)
        return 1
    if not PANTHEON_CSV.exists():
        print(f"pantheon 2.0 csv not found: {PANTHEON_CSV}", file=sys.stderr)
        return 1
    if not CROSS_VERIFIED_GZ.exists():
        print(f"cross-verified gz not found: {CROSS_VERIFIED_GZ}", file=sys.stderr)
        return 1

    pantheon_qids = load_qids_from_csv(PANTHEON_CSV, "wd_id", total_hint=126_582)
    print(f"pantheon 2.0 unique QIDs: {len(pantheon_qids):,}")

    cv_qids = load_qids_from_gz(CROSS_VERIFIED_GZ, "wikidata_code", total_hint=2_291_817)
    print(f"cross-verified unique QIDs: {len(cv_qids):,}")

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        ensure_column(conn, "pantheon_2_db")
        ensure_column(conn, "cross_verified_db")

        with conn:
            n_p = flag_qids(conn, "pantheon_2_db", pantheon_qids)
        print(f"pantheon_2_db rows flagged: {n_p:,}")

        with conn:
            n_cv = flag_qids(conn, "cross_verified_db", cv_qids)
        print(f"cross_verified_db rows flagged: {n_cv:,}")

        totals = conn.execute(
            "SELECT "
            "  SUM(pantheon_2_db), "
            "  SUM(cross_verified_db), "
            "  SUM(CASE WHEN pantheon_2_db = 1 AND cross_verified_db = 1 THEN 1 ELSE 0 END), "
            "  COUNT(*) "
            "FROM individuals"
        ).fetchone()
        print(
            "individuals: total={3:,} pantheon_2_db=1: {0:,} cross_verified_db=1: {1:,} both=1: {2:,}".format(
                *totals
            )
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
