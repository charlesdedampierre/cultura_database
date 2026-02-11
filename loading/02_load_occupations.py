"""Load occupations and individual-occupation mappings into SQLite.

Reads: occupations.json, individual_occupations.json
Creates: occupations, individual_occupations tables
"""

import json
import os
import sqlite3

from tqdm import tqdm
from utils import EXTRACTED_DIR, get_db_connection

INDIVIDUALS_DIR = os.path.join(EXTRACTED_DIR, "individuals")


def create_tables(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS occupations (
            occupation_wikidata_id TEXT PRIMARY KEY,
            occupation_name        TEXT,
            occupation_category    TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS individual_occupations (
            wikidata_id            TEXT,
            occupation_wikidata_id TEXT
        )
    """)
    conn.commit()


def main():
    conn = get_db_connection()
    create_tables(conn)

    conn.execute("DELETE FROM occupations")
    conn.execute("DELETE FROM individual_occupations")

    # Load occupations
    with open(os.path.join(INDIVIDUALS_DIR, "occupations.json")) as f:
        occupations = json.load(f)

    occ_rows = [
        (o["occupation_wikidata_id"], o["occupation_name"], o["occupation_category"])
        for o in occupations
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO occupations VALUES (?, ?, ?)",
        occ_rows,
    )

    # Load individual-occupation mappings
    with open(os.path.join(INDIVIDUALS_DIR, "individual_occupations.json")) as f:
        ind_occs = json.load(f)

    io_rows = [(io["wikidata_id"], io["occupation_wikidata_id"]) for io in ind_occs]
    conn.executemany(
        "INSERT INTO individual_occupations VALUES (?, ?)",
        io_rows,
    )

    conn.commit()

    occ_count = conn.execute("SELECT COUNT(*) FROM occupations").fetchone()[0]
    io_count = conn.execute("SELECT COUNT(*) FROM individual_occupations").fetchone()[0]
    print(f"Loaded {occ_count} occupations, {io_count} individual-occupation mappings")

    conn.close()


if __name__ == "__main__":
    main()
