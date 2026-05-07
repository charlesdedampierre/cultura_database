"""Enrich country_of_citizenship with the full Wikidata P31 list per polity.

Why
---
`country_of_citizenship.instance_of` only carries one of 13 whitelisted
country/territory labels (sovereign state, historical country, realm, ...);
the fine-grained Wikidata types like kingdom, empire, duchy, caliphate,
dynasty, principality were dropped at integration time. The
``data/all_humans/p27_countries_wikidata_expanded.tsv`` file already has
the *full* pipe-separated P31 list per polity (columns ``instance_qids``
and ``instance_labels``) — this script copies that information back into
``country_of_citizenship`` as two new columns.

Behaviour
---------
- Adds two columns if missing:
    instance_qids   TEXT  (pipe-separated Wikidata Q-ids of all P31 values)
    instance_labels TEXT  (pipe-separated English labels matching instance_qids)
- For every Q-id in the TSV, INSERTs a new country_of_citizenship row if it
  is missing (so we *gain* polities, never lose them).
- For every Q-id already in country_of_citizenship, UPDATEs only the two
  new columns. The existing ``instance_of`` (the whitelisted bucket label)
  is left untouched.
"""

from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "humans_clean.sqlite3"
TSV_PATH = ROOT / "data" / "all_humans" / "p27_countries_wikidata_expanded.tsv"


def ensure_columns(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(country_of_citizenship)").fetchall()}
    for col in ("instance_qids", "instance_labels"):
        if col not in cols:
            conn.execute(f"ALTER TABLE country_of_citizenship ADD COLUMN {col} TEXT")
            print(f"added column country_of_citizenship.{col}")
        else:
            print(f"column country_of_citizenship.{col} already exists")


def load_tsv() -> list[dict[str, str]]:
    with TSV_PATH.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        rows = []
        for r in tqdm(reader, desc=f"reading {TSV_PATH.name}"):
            qid = (r.get("qid") or "").strip()
            if qid.startswith("Q"):
                rows.append(r)
    return rows


def main() -> int:
    if not DB_PATH.exists():
        print(f"database not found: {DB_PATH}", file=sys.stderr)
        return 1
    if not TSV_PATH.exists():
        print(f"tsv not found: {TSV_PATH}", file=sys.stderr)
        return 1

    rows = load_tsv()
    print(f"polities in tsv: {len(rows):,}")

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        ensure_columns(conn)

        existing = {
            qid for (qid,) in conn.execute(
                "SELECT wikidata_id FROM country_of_citizenship"
            )
        }
        print(f"existing country_of_citizenship rows: {len(existing):,}")

        n_inserted = 0
        n_updated = 0
        with conn:
            for r in tqdm(rows, desc="upserting"):
                qid = r["qid"].strip()
                label = (r.get("label") or "").strip() or None
                wiki = (r.get("wikipedia_url") or "").strip() or None
                inst_qids = (r.get("instance_qids") or "").strip() or None
                inst_labels = (r.get("instance_labels") or "").strip() or None

                if qid in existing:
                    conn.execute(
                        "UPDATE country_of_citizenship "
                        "SET instance_qids = ?, instance_labels = ? "
                        "WHERE wikidata_id = ?",
                        (inst_qids, inst_labels, qid),
                    )
                    n_updated += 1
                else:
                    conn.execute(
                        "INSERT INTO country_of_citizenship "
                        "(wikidata_id, name_en, instance_qids, instance_labels, "
                        " en_wikipedia_url) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (qid, label, inst_qids, inst_labels, wiki),
                    )
                    n_inserted += 1

        print(f"rows inserted (new polities): {n_inserted:,}")
        print(f"rows updated (existing polities): {n_updated:,}")

        total = conn.execute("SELECT COUNT(*) FROM country_of_citizenship").fetchone()[0]
        with_qids = conn.execute(
            "SELECT COUNT(*) FROM country_of_citizenship WHERE instance_qids IS NOT NULL"
        ).fetchone()[0]
        print(f"total country_of_citizenship rows: {total:,}")
        print(f"  with instance_qids populated: {with_qids:,}")

        print("\nsample (kingdoms):")
        for r in conn.execute(
            "SELECT wikidata_id, name_en, instance_of, instance_labels "
            "FROM country_of_citizenship "
            "WHERE instance_labels LIKE '%kingdom%' "
            "LIMIT 8"
        ):
            print(f"  {r}")

    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
