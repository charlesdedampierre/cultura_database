"""Load Wikipedia sitelinks into SQLite.

Reads: sitelinks.json
Creates: individual_sitelinks table
"""

import json
import os
import sqlite3

from tqdm import tqdm
from utils import EXTRACTED_DIR, get_db_connection

INDIVIDUALS_DIR = os.path.join(EXTRACTED_DIR, "individuals")


def create_tables(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS individual_sitelinks (
            wikidata_id TEXT,
            url         TEXT,
            language    TEXT
        )
    """)
    conn.commit()


def main():
    conn = get_db_connection()
    create_tables(conn)

    conn.execute("DELETE FROM individual_sitelinks")

    sitelinks_path = os.path.join(INDIVIDUALS_DIR, "sitelinks.json")
    with open(sitelinks_path) as f:
        sitelinks_data = json.load(f)

    rows = []
    for entry in tqdm(sitelinks_data, desc="Loading sitelinks"):
        wid = entry["wikidata_id"]
        for sl in entry.get("sitelinks", []):
            rows.append((wid, sl["url"], sl["language"]))

    conn.executemany("INSERT INTO individual_sitelinks VALUES (?, ?, ?)", rows)
    conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM individual_sitelinks").fetchone()[0]
    print(f"Loaded {count} sitelink records")

    conn.close()


if __name__ == "__main__":
    main()
