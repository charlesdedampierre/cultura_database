"""Final cleaning: filter individuals and create the individuals_kept table.

Filters:
- Must have birthyear
- Name must not start with "Q" (unresolved Wikidata IDs)
- Name must not contain "Painter" (fake entries)
- Must have at least one region assignment
- Must have at least one external identifier

Creates: individuals_kept table
"""

import os
import sqlite3
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "loading"))
from utils import get_db_connection


def create_tables(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS individuals_kept (
            wikidata_id TEXT PRIMARY KEY
        )
    """)
    conn.commit()


def main():
    conn = get_db_connection()
    create_tables(conn)
    conn.execute("DELETE FROM individuals_kept")

    # Load individuals
    df_ind = pd.read_sql_query("SELECT wikidata_id, name, birthyear FROM individuals", conn)
    total = len(df_ind)
    print(f"Total individuals: {total}")

    # Filter: must have birthyear
    df_ind = df_ind[df_ind["birthyear"].notna()]
    print(f"  After birthyear filter: {len(df_ind)}")

    # Filter: name must not start with Q (unresolved Wikidata IDs)
    df_ind = df_ind[~df_ind["name"].str.startswith("Q", na=False)]
    print(f"  After Q-name filter: {len(df_ind)}")

    # Filter: name must not contain "Painter"
    df_ind = df_ind[~df_ind["name"].str.contains("Painter", na=False)]
    print(f"  After Painter filter: {len(df_ind)}")

    # Filter: must have regions
    ids_with_regions = pd.read_sql_query(
        "SELECT DISTINCT wikidata_id FROM individual_regions", conn
    )
    df_ind = df_ind[df_ind["wikidata_id"].isin(ids_with_regions["wikidata_id"])]
    print(f"  After region filter: {len(df_ind)}")

    # Filter: must have identifiers
    ids_with_identifiers = pd.read_sql_query(
        "SELECT DISTINCT wikidata_id FROM individual_identifiers", conn
    )
    df_ind = df_ind[df_ind["wikidata_id"].isin(ids_with_identifiers["wikidata_id"])]
    print(f"  After identifier filter: {len(df_ind)}")

    # Insert kept individuals
    kept_ids = [(wid,) for wid in df_ind["wikidata_id"]]
    conn.executemany("INSERT INTO individuals_kept VALUES (?)", kept_ids)
    conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM individuals_kept").fetchone()[0]
    print(f"\nFinal individuals_kept: {count}")

    conn.close()


if __name__ == "__main__":
    main()
