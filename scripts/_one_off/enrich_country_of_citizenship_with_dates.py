"""Enrich country_of_citizenship with inception / dissolution dates.

Source: ``data/all_humans/p27_countries_wikidata_expanded.tsv`` (columns
``inception`` and ``dissolved``, raw ISO strings from Wikidata such as
``1963-01-01T00:00:00Z`` or ``-0446-01-01T00:00:00Z``).

Behaviour
---------
- Adds two TEXT columns to country_of_citizenship if missing:
    inception   TEXT  (raw ISO timestamp from Wikidata, NULL if absent)
    dissolved   TEXT  (raw ISO timestamp from Wikidata, NULL if absent)
- For every Q-id already in the table, UPDATEs only those two columns.
- Wikidata "unknown value" placeholders (genid URLs) are stored as NULL.
- Existing rows that are not present in the TSV (98 polities, mostly cities
  or modern entities Q-ids without P31 country class) are left untouched.
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
    for col in ("inception", "dissolved"):
        if col not in cols:
            conn.execute(f"ALTER TABLE country_of_citizenship ADD COLUMN {col} TEXT")
            print(f"added column country_of_citizenship.{col}")
        else:
            print(f"column country_of_citizenship.{col} already exists")


def clean(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    # Wikidata "unknown value" placeholders look like a genid URL.
    if "genid" in v:
        return None
    return v


def load_tsv() -> dict[str, tuple[str | None, str | None]]:
    out: dict[str, tuple[str | None, str | None]] = {}
    with TSV_PATH.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for r in tqdm(reader, desc=f"reading {TSV_PATH.name}"):
            qid = (r.get("qid") or "").strip()
            if not qid.startswith("Q"):
                continue
            out[qid] = (clean(r.get("inception")), clean(r.get("dissolved")))
    return out


def main() -> int:
    if not DB_PATH.exists():
        print(f"database not found: {DB_PATH}", file=sys.stderr)
        return 1
    if not TSV_PATH.exists():
        print(f"tsv not found: {TSV_PATH}", file=sys.stderr)
        return 1

    dates = load_tsv()
    print(f"polities in tsv: {len(dates):,}")

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        ensure_columns(conn)

        existing = [
            qid for (qid,) in conn.execute(
                "SELECT wikidata_id FROM country_of_citizenship"
            )
        ]
        print(f"existing country_of_citizenship rows: {len(existing):,}")

        n_updated = 0
        n_no_data = 0
        with conn:
            for qid in tqdm(existing, desc="updating"):
                if qid not in dates:
                    n_no_data += 1
                    continue
                inception, dissolved = dates[qid]
                conn.execute(
                    "UPDATE country_of_citizenship "
                    "SET inception = ?, dissolved = ? "
                    "WHERE wikidata_id = ?",
                    (inception, dissolved, qid),
                )
                n_updated += 1

        print(f"rows updated: {n_updated:,}")
        print(f"rows with no matching tsv entry: {n_no_data:,}")

        total = conn.execute("SELECT COUNT(*) FROM country_of_citizenship").fetchone()[0]
        with_inc = conn.execute(
            "SELECT COUNT(*) FROM country_of_citizenship WHERE inception IS NOT NULL"
        ).fetchone()[0]
        with_dis = conn.execute(
            "SELECT COUNT(*) FROM country_of_citizenship WHERE dissolved IS NOT NULL"
        ).fetchone()[0]
        print(f"total country_of_citizenship rows: {total:,}")
        print(f"  with inception populated: {with_inc:,}")
        print(f"  with dissolved populated: {with_dis:,}")

        print("\nsample:")
        for r in conn.execute(
            "SELECT wikidata_id, name_en, inception, dissolved "
            "FROM country_of_citizenship "
            "WHERE inception IS NOT NULL OR dissolved IS NOT NULL "
            "ORDER BY count DESC LIMIT 8"
        ):
            print(f"  {r}")

    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
