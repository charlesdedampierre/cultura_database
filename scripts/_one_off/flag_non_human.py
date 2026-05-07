"""Add a `non_human` flag to individuals based on Wikidata P31 (instance of).

Background
----------
Our cohort is built from `?h wdt:P31 wd:Q5` (instance of human), but Wikidata
entities can carry multiple P31 values. A subset of cohort members are
*also* declared as fictional characters, mythical characters, deities,
legendary creatures, etc. Laouenan et al. (2022) call these
"pseudo-individuals" and remove them from the cross-verified database via
name-pattern heuristics. We do the same here, but using the authoritative
Wikidata P31 declarations.

Targets (P31 values that mark an entity as non-human even when also Q5):
    Q95074      fictional character
    Q4271324    mythical character
    Q178885     deity
    Q15632617   fictional human
    Q21070568   human biblical figure
    Q24334685   legendary creature

The script:
  1. For each P31 above, streams the full Q-id set from QLever.
  2. Intersects with `individuals.wikidata_id`.
  3. Adds `non_human INTEGER NOT NULL DEFAULT 0` to `individuals` if missing,
     and sets it to 1 for the matched Q-ids.
  4. Creates an index on the column.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "wikidata_extraction_scripts_v2"))
from wikidata import extract_qid, qlever_stream  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "humans_clean.sqlite3"

NON_HUMAN_P31: dict[str, str] = {
    "Q95074":     "fictional character",
    "Q4271324":   "mythical character",
    "Q178885":    "deity",
    "Q15632617":  "fictional human",
    "Q21070568":  "human biblical figure",
    "Q24334685":  "legendary creature",
}

PULL_QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT DISTINCT ?h WHERE {{
  ?h wdt:P31 wd:{qid} .
}}
"""

BATCH = 50_000


def pull_qids(p31_qid: str, label: str) -> set[str]:
    qids: set[str] = set()
    desc = f"{p31_qid} ({label})"
    for row in tqdm(qlever_stream(PULL_QUERY.format(qid=p31_qid)),
                    desc=desc, unit=" qid"):
        if not row:
            continue
        qid = extract_qid(row[0])
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


def ensure_index(conn: sqlite3.Connection, column: str) -> None:
    idx = f"idx_individuals_{column}"
    conn.execute(f"CREATE INDEX IF NOT EXISTS {idx} ON individuals({column})")


def flag_qids(conn: sqlite3.Connection, column: str, qids: set[str]) -> int:
    conn.execute(f"UPDATE individuals SET {column} = 0")
    if not qids:
        return 0
    conn.execute("CREATE TEMP TABLE _qids (wikidata_id TEXT PRIMARY KEY)")
    qid_list = list(qids)
    for i in tqdm(range(0, len(qid_list), BATCH), desc=f"staging {column} qids"):
        chunk = qid_list[i : i + BATCH]
        conn.executemany(
            "INSERT OR IGNORE INTO _qids(wikidata_id) VALUES (?)",
            ((q,) for q in chunk),
        )
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

    print("[1/3] pulling non-human P31 Q-id sets from QLever")
    all_qids: set[str] = set()
    per_class: dict[str, int] = {}
    for qid, label in NON_HUMAN_P31.items():
        s = pull_qids(qid, label)
        per_class[f"{qid} ({label})"] = len(s)
        all_qids |= s
        print(f"  {qid} ({label}): {len(s):,} (running union: {len(all_qids):,})")

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        ensure_column(conn, "non_human")

        print("[2/3] flagging individuals.non_human")
        with conn:
            n = flag_qids(conn, "non_human", all_qids)
        print(f"  rows flagged non_human=1: {n:,}")

        print("[3/3] indexing individuals.non_human")
        ensure_index(conn, "non_human")

        totals = conn.execute(
            "SELECT "
            "  COUNT(*), "
            "  SUM(non_human), "
            "  SUM(CASE WHEN non_human=1 AND cross_verified_db=1 THEN 1 ELSE 0 END), "
            "  SUM(CASE WHEN non_human=1 AND cross_verified_db=0 THEN 1 ELSE 0 END) "
            "FROM individuals"
        ).fetchone()
        print(
            "individuals: total={0:,}  non_human=1: {1:,}  "
            "non_human & in cross-verified: {2:,}  "
            "non_human & NOT in cross-verified: {3:,}".format(*totals)
        )
        print("\nQLever pull sizes (Wikidata-wide, before intersect with cohort):")
        for k, v in per_class.items():
            print(f"  {k}: {v:,}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
