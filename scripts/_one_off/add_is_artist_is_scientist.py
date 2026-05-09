"""
Add is_artist / is_scientist boolean columns to individuals in humans_clean.duckdb.

Source of truth: occupations.meta_occupation in /Users/charlesdedampierre/Desktop/humans_clean07_05.sqlite3
Mapping: split individuals.occupations_en on ';', join on occupations.name_en,
         OR-aggregate per wikidata_id (handles the 2 conflicting names — iconographer, logographer).
"""

from __future__ import annotations

import time
from pathlib import Path

import duckdb
import pandas as pd
import sqlite3

REPO_ROOT = Path(__file__).resolve().parents[2]
DUCKDB_PATH = REPO_ROOT / "data" / "humans_clean.duckdb"
SQLITE_PATH = Path("/Users/charlesdedampierre/Desktop/humans_clean07_05.sqlite3")


def load_meta_occupation_lookup() -> pd.DataFrame:
    with sqlite3.connect(SQLITE_PATH) as src:
        df = pd.read_sql_query(
            """
            SELECT name_en, meta_occupation
            FROM occupations
            WHERE meta_occupation IS NOT NULL
              AND name_en IS NOT NULL
            """,
            src,
        )
    return df


def main() -> None:
    print(f"DuckDB:  {DUCKDB_PATH}")
    print(f"SQLite:  {SQLITE_PATH}")

    lookup = load_meta_occupation_lookup()
    print(f"Loaded {len(lookup):,} (name_en, meta_occupation) rows from sqlite")
    print(lookup["meta_occupation"].value_counts().to_string())

    con = duckdb.connect(str(DUCKDB_PATH))
    con.register("meta_occ_lookup", lookup)

    cols = {r[1] for r in con.execute("PRAGMA table_info('individuals')").fetchall()}
    if "is_artist" not in cols:
        con.execute("ALTER TABLE individuals ADD COLUMN is_artist BOOLEAN")
        print("Added column: is_artist")
    if "is_scientist" not in cols:
        con.execute("ALTER TABLE individuals ADD COLUMN is_scientist BOOLEAN")
        print("Added column: is_scientist")

    print("Building per-individual flags...")
    t0 = time.time()
    con.execute("""
        CREATE OR REPLACE TEMP TABLE _ind_meta AS
        WITH exploded AS (
            SELECT
                wikidata_id,
                TRIM(unnest(string_split(occupations_en, ';'))) AS occ_name
            FROM individuals
            WHERE occupations_en IS NOT NULL
        ),
        joined AS (
            SELECT e.wikidata_id, l.meta_occupation
            FROM exploded e
            JOIN meta_occ_lookup l ON e.occ_name = l.name_en
        )
        SELECT
            wikidata_id,
            BOOL_OR(meta_occupation = 'artist')    AS is_artist,
            BOOL_OR(meta_occupation = 'scientist') AS is_scientist
        FROM joined
        GROUP BY wikidata_id
    """)
    n_flagged = con.execute("SELECT COUNT(*) FROM _ind_meta").fetchone()[0]
    print(f"  flagged individuals: {n_flagged:,} ({time.time()-t0:.1f}s)")

    print("Updating individuals table...")
    t0 = time.time()
    con.execute("""
        UPDATE individuals AS i
        SET is_artist    = COALESCE(m.is_artist,    FALSE),
            is_scientist = COALESCE(m.is_scientist, FALSE)
        FROM _ind_meta AS m
        WHERE i.wikidata_id = m.wikidata_id
    """)
    con.execute("""
        UPDATE individuals
        SET is_artist = FALSE
        WHERE is_artist IS NULL
    """)
    con.execute("""
        UPDATE individuals
        SET is_scientist = FALSE
        WHERE is_scientist IS NULL
    """)
    print(f"  update done ({time.time()-t0:.1f}s)")

    print("\nVerification:")
    print(con.execute("""
        SELECT
            COUNT(*)                                          AS total,
            SUM(CASE WHEN is_artist    THEN 1 ELSE 0 END)     AS n_artist,
            SUM(CASE WHEN is_scientist THEN 1 ELSE 0 END)     AS n_scientist,
            SUM(CASE WHEN is_artist AND is_scientist THEN 1 ELSE 0 END) AS n_both
        FROM individuals
    """).fetchdf().to_string(index=False))

    con.close()
    print("Done.")


if __name__ == "__main__":
    main()
