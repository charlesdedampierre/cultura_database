"""22 — Add inception (P571) / dissolution (P576) dates to the `places` table.

Reads ``data/all_humans/wikidata_extraction_scripts_v2/place_dates.json``
(produced by ``scripts/wikidata_extraction_scripts_v2/20_extract_place_dates.py``)
and writes four new columns onto ``places`` in the canonical DuckDB:

    inception_date         TEXT     ISO timestamp (e.g. "1492-10-12T00:00:00Z")
    inception_precision    INTEGER  Wikidata precision code (11=day .. 6=millennium)
    dissolution_date       TEXT
    dissolution_precision  INTEGER

This mirrors the (inception_date, inception_precision) convention already
used by the ``works`` table.

Strategy
--------
- 64,793 places have at least one date — small enough for a single in-memory
  join. We bench it on a sample first, then do the full update.
- Writes go directly to ``data/humans_clean.duckdb`` (per the project's
  "always use duck" rule for the canonical DB), bypassing the SQLite
  intermediate used by the older numbered scripts.

Usage
-----
    python scripts/database_integration_scripts_V2/22_add_dates_to_places.py --bench
    python scripts/database_integration_scripts_V2/22_add_dates_to_places.py
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import duckdb
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "humans_clean.duckdb"
JSON_PATH = ROOT / "data" / "all_humans" / "wikidata_extraction_scripts_v2" / "place_dates.json"

NEW_COLS = [
    ("inception_date", "VARCHAR"),
    ("inception_precision", "INTEGER"),
    ("dissolution_date", "VARCHAR"),
    ("dissolution_precision", "INTEGER"),
]


def load_rows(json_path: Path) -> list[tuple]:
    """Load place_dates.json and return rows ready for insertion."""
    with json_path.open() as fh:
        raw = json.load(fh)
    rows = []
    for qid, dates in tqdm(raw.items(), desc="parse JSON", unit="place"):
        inc = dates.get("inception")
        dis = dates.get("dissolution")
        if inc is None and dis is None:
            continue
        rows.append((
            qid,
            inc["date"] if inc else None,
            inc["precision"] if inc else None,
            dis["date"] if dis else None,
            dis["precision"] if dis else None,
        ))
    return rows


def add_columns(con: duckdb.DuckDBPyConnection) -> None:
    """Idempotent: add each column only if missing."""
    existing = {r[0] for r in con.execute("DESCRIBE places").fetchall()}
    for name, sql_type in NEW_COLS:
        if name in existing:
            print(f"  column already present: {name}")
        else:
            con.execute(f"ALTER TABLE places ADD COLUMN {name} {sql_type}")
            print(f"  + added column: {name} {sql_type}")


def write_dates(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> int:
    """Bulk-update places via a temp staging table + UPDATE FROM."""
    con.execute("DROP TABLE IF EXISTS _place_dates_staging")
    con.execute(
        """
        CREATE TEMP TABLE _place_dates_staging (
            id VARCHAR,
            inception_date VARCHAR,
            inception_precision INTEGER,
            dissolution_date VARCHAR,
            dissolution_precision INTEGER
        )
        """
    )
    # Bulk insert via VALUES is slow at this scale — use a parquet/df bridge.
    import pandas as pd
    df = pd.DataFrame(rows, columns=[
        "id", "inception_date", "inception_precision",
        "dissolution_date", "dissolution_precision",
    ])
    con.register("_pd_df", df)
    con.execute("INSERT INTO _place_dates_staging SELECT * FROM _pd_df")
    con.unregister("_pd_df")

    n_staged = con.execute("SELECT COUNT(*) FROM _place_dates_staging").fetchone()[0]
    print(f"  staged: {n_staged:,} rows")

    n_matched = con.execute(
        """
        SELECT COUNT(*) FROM _place_dates_staging s
        JOIN places p ON p.id = s.id
        """
    ).fetchone()[0]
    print(f"  matched to existing places: {n_matched:,}")

    # Single UPDATE for all four columns.
    con.execute(
        """
        UPDATE places
        SET inception_date         = s.inception_date,
            inception_precision    = s.inception_precision,
            dissolution_date       = s.dissolution_date,
            dissolution_precision  = s.dissolution_precision
        FROM _place_dates_staging s
        WHERE places.id = s.id
        """
    )
    con.execute("DROP TABLE _place_dates_staging")
    return n_matched


def report(con: duckdb.DuckDBPyConnection) -> None:
    n_total = con.execute("SELECT COUNT(*) FROM places").fetchone()[0]
    n_inc = con.execute("SELECT COUNT(*) FROM places WHERE inception_date IS NOT NULL").fetchone()[0]
    n_dis = con.execute("SELECT COUNT(*) FROM places WHERE dissolution_date IS NOT NULL").fetchone()[0]
    n_any = con.execute(
        "SELECT COUNT(*) FROM places WHERE inception_date IS NOT NULL OR dissolution_date IS NOT NULL"
    ).fetchone()[0]
    print(f"  places total            : {n_total:,}")
    print(f"  with inception_date     : {n_inc:,}")
    print(f"  with dissolution_date   : {n_dis:,}")
    print(f"  with at least one date  : {n_any:,}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bench", action="store_true",
                        help="Sample 1,000 places, time the write, do not commit.")
    args = parser.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"missing DB: {DB_PATH}")
    if not JSON_PATH.exists():
        raise SystemExit(f"missing JSON: {JSON_PATH}")

    print(f"DB   : {DB_PATH}")
    print(f"JSON : {JSON_PATH}")

    rows = load_rows(JSON_PATH)
    print(f"parsed {len(rows):,} dated places from JSON")

    if args.bench:
        sample = rows[:1_000]
        with duckdb.connect(":memory:") as con:
            con.execute("ATTACH '" + str(DB_PATH) + "' AS src (READ_ONLY)")
            con.execute("CREATE TABLE places AS SELECT * FROM src.places LIMIT 50000")
            add_columns(con)
            t0 = time.perf_counter()
            n = write_dates(con, sample)
            elapsed = time.perf_counter() - t0
            print(f"  bench: wrote {n:,} of {len(sample):,} sample rows in {elapsed:.2f}s")
            est_full = elapsed * (len(rows) / max(len(sample), 1))
            print(f"  bench: estimated full-run time ≈ {est_full:.1f}s")
        return

    with duckdb.connect(str(DB_PATH)) as con:
        print("Adding columns…")
        add_columns(con)
        print("Writing dates…")
        t0 = time.perf_counter()
        n = write_dates(con, rows)
        print(f"  updated {n:,} rows in {time.perf_counter() - t0:.1f}s")
        print("Final coverage:")
        report(con)


if __name__ == "__main__":
    main()
