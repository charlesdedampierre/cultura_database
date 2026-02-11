"""Load death year data into SQLite.

Reads: deathyears.json
Creates: deathyear table
"""

import json
import os
import sqlite3

from tqdm import tqdm
from utils import EXTRACTED_DIR, get_db_connection

INDIVIDUALS_DIR = os.path.join(EXTRACTED_DIR, "individuals")


def create_tables(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS deathyear (
            wikidata_id TEXT,
            deathyear   INTEGER
        )
    """)
    conn.commit()


def main():
    conn = get_db_connection()
    create_tables(conn)

    conn.execute("DELETE FROM deathyear")

    deathyears_path = os.path.join(INDIVIDUALS_DIR, "deathyears.json")
    with open(deathyears_path) as f:
        deathyears = json.load(f)

    rows = [(d["wikidata_id"], d["deathyear"]) for d in deathyears]

    conn.executemany("INSERT INTO deathyear VALUES (?, ?)", rows)
    conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM deathyear").fetchone()[0]
    print(f"Loaded {count} death year records")

    conn.close()


if __name__ == "__main__":
    main()
