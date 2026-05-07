"""Flag CV-via-redirect individuals already present in Cultura.

For canonical Wikidata QIDs that:
  - are already in humans_clean.individuals, AND
  - correspond to a CV `wikidata_code` that was redirected by Wikidata to that
    canonical QID,
we set:
  - cross_verified_db = 1
  - birthdate_from_CV / deathdate_from_CV (filled from CV's old-QID row,
    only when currently NULL — never overwrites previously-written values)

Bench-then-run on humans_clean.sqlite3.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import duckdb
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/humans_clean.sqlite3"
RES = ROOT / "data/cv_missing_from_cultura/qid_resolution.json"
CV_CSV = ROOT / "data/similar_databases/cross-verified-database/cross-verified-database.utf8.csv.gz"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Plan only — print counts but do not write.")
    args = parser.parse_args()

    print("[load] resolution map")
    resolution = json.loads(RES.read_text())

    # canonical -> first old QID (we keep one CV row per canonical for date fill)
    canon_to_old: dict[str, str] = {}
    for old, info in resolution.items():
        if not info["exists"]:
            continue
        new = info["redirect"] or old
        if new == old:
            continue  # not a redirect
        canon_to_old.setdefault(new, old)

    print(f"[load] {len(canon_to_old):,} canonical QIDs come from a redirected CV row")

    # Identify which are already in Cultura
    print("[scan] which canonical QIDs are already in individuals...")
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = NORMAL;")
    cur.execute("PRAGMA temp_store = MEMORY;")

    cur.execute("CREATE TEMP TABLE candidates(canon TEXT PRIMARY KEY, old_qid TEXT) WITHOUT ROWID;")
    cur.executemany(
        "INSERT INTO candidates(canon, old_qid) VALUES (?, ?);",
        list(canon_to_old.items()),
    )
    cur.execute("CREATE INDEX cand_old ON candidates(old_qid);")

    n_in_cult = cur.execute(
        "SELECT COUNT(*) FROM candidates c "
        "JOIN individuals i ON i.wikidata_id = c.canon"
    ).fetchone()[0]
    n_already_cv = cur.execute(
        "SELECT COUNT(*) FROM candidates c "
        "JOIN individuals i ON i.wikidata_id = c.canon "
        "WHERE i.cross_verified_db = 1"
    ).fetchone()[0]
    print(f"  in Cultura individuals    : {n_in_cult:>6,}")
    print(f"  already cross_verified_db=1: {n_already_cv:>6,}")
    print(f"  to set cross_verified_db=1: {n_in_cult - n_already_cv:>6,}")

    # Pull CV dates for the relevant old QIDs via DuckDB
    print("[load] CV birth/death years for relevant old QIDs...")
    old_qids = list(canon_to_old.values())
    dcon = duckdb.connect()
    dcon.execute(f"""
        CREATE TEMP TABLE cv AS
        SELECT wikidata_code AS qid,
               CASE WHEN TRY_CAST(birth AS INTEGER) IS NOT NULL
                    THEN CAST(TRY_CAST(birth AS INTEGER) AS VARCHAR) END AS birth,
               CASE WHEN TRY_CAST(death AS INTEGER) IS NOT NULL
                    THEN CAST(TRY_CAST(death AS INTEGER) AS VARCHAR) END AS death
        FROM read_csv_auto('{CV_CSV}', header=true, ignore_errors=true);
    """)
    import polars as pl_
    dcon.register("targets", pl_.DataFrame({"qid": old_qids}))
    cv_rows = dcon.execute("""
        SELECT cv.qid, cv.birth, cv.death
        FROM cv JOIN targets t ON t.qid = cv.qid;
    """).fetchall()
    cv_dates = {r[0]: (r[1], r[2]) for r in cv_rows}
    dcon.close()
    print(f"[load] CV dates loaded for {len(cv_dates):,} old QIDs")

    # Build update payload: (canon_qid, b, d) for each candidate already in Cultura
    rows = cur.execute(
        "SELECT c.canon, c.old_qid FROM candidates c "
        "JOIN individuals i ON i.wikidata_id = c.canon"
    ).fetchall()
    updates = []
    for canon, old in rows:
        b, d = cv_dates.get(old, (None, None))
        updates.append((1, b, d, canon))

    print(f"[plan] would write {len(updates):,} UPDATE rows "
          f"(set cross_verified_db=1; fill birth/death_from_CV when NULL)")

    if args.dry_run:
        return

    # Use a staging table to do this efficiently with UPDATE FROM
    cur.execute("DROP TABLE IF EXISTS _cv_redirect_updates;")
    cur.execute(
        "CREATE TEMP TABLE _cv_redirect_updates "
        "(canon TEXT PRIMARY KEY, b TEXT, d TEXT) WITHOUT ROWID;"
    )
    BATCH = 50_000
    for i in tqdm(range(0, len(updates), BATCH), desc="stage"):
        chunk = [(c, b, d) for (_, b, d, c) in updates[i:i+BATCH]]
        cur.executemany(
            "INSERT INTO _cv_redirect_updates(canon, b, d) VALUES (?, ?, ?);",
            chunk,
        )

    print("[write] applying UPDATE FROM...")
    t = time.perf_counter()
    cur.execute(
        """
        UPDATE individuals
           SET cross_verified_db = 1,
               birthdate_from_CV = COALESCE(birthdate_from_CV,
                   (SELECT b FROM _cv_redirect_updates WHERE canon = individuals.wikidata_id)),
               deathdate_from_CV = COALESCE(deathdate_from_CV,
                   (SELECT d FROM _cv_redirect_updates WHERE canon = individuals.wikidata_id))
         WHERE wikidata_id IN (SELECT canon FROM _cv_redirect_updates);
        """
    )
    con.commit()
    print(f"[write] done in {time.perf_counter()-t:.1f}s")

    # Verify
    new_total_cv = cur.execute(
        "SELECT COUNT(*) FROM individuals WHERE cross_verified_db = 1"
    ).fetchone()[0]
    print(f"\n  cross_verified_db=1 individuals (after): {new_total_cv:,}")
    con.close()


if __name__ == "__main__":
    main()
