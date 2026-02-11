"""Load external identifiers into SQLite.

Reads: individual_identifiers.json
Creates: identifiers, individual_identifiers tables
Updates: individuals.identifier_count
"""

import json
import os
import sqlite3
from collections import Counter

from tqdm import tqdm
from utils import EXTRACTED_DIR, get_db_connection

INDIVIDUALS_DIR = os.path.join(EXTRACTED_DIR, "individuals")


def create_tables(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS identifiers (
            identifier_wikidata_id TEXT PRIMARY KEY,
            identifier_name        TEXT,
            country_wikidata_id    TEXT,
            country_name           TEXT,
            identifier_url         TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS individual_identifiers (
            wikidata_id            TEXT,
            identifier_wikidata_id TEXT
        )
    """)
    conn.commit()


def main():
    conn = get_db_connection()
    create_tables(conn)

    conn.execute("DELETE FROM identifiers")
    conn.execute("DELETE FROM individual_identifiers")

    identifiers_path = os.path.join(INDIVIDUALS_DIR, "individual_identifiers.json")
    with open(identifiers_path) as f:
        identifiers_data = json.load(f)

    # Collect unique identifiers and individual mappings
    all_identifiers = {}
    ind_id_rows = []
    identifier_counts = Counter()

    for entry in tqdm(identifiers_data, desc="Loading identifiers"):
        wid = entry["wikidata_id"]
        for ident in entry.get("identifiers", []):
            iid = ident["identifier_wikidata_id"]

            if iid not in all_identifiers:
                all_identifiers[iid] = {
                    "identifier_wikidata_id": iid,
                    "identifier_name": ident["identifier_name"],
                }

            ind_id_rows.append((wid, iid))
            identifier_counts[wid] += 1

    # Insert unique identifiers
    id_rows = [
        (v["identifier_wikidata_id"], v["identifier_name"], None, None, None)
        for v in all_identifiers.values()
    ]
    conn.executemany("INSERT OR REPLACE INTO identifiers VALUES (?, ?, ?, ?, ?)", id_rows)

    # Insert individual-identifier mappings
    conn.executemany("INSERT INTO individual_identifiers VALUES (?, ?)", ind_id_rows)

    # Update identifier counts on individuals table
    update_rows = [(count, wid) for wid, count in identifier_counts.items()]
    conn.executemany(
        "UPDATE individuals SET identifier_count = ? WHERE wikidata_id = ?",
        update_rows,
    )

    conn.commit()

    id_count = conn.execute("SELECT COUNT(*) FROM identifiers").fetchone()[0]
    ii_count = conn.execute("SELECT COUNT(*) FROM individual_identifiers").fetchone()[0]
    print(f"Loaded {id_count} unique identifiers, {ii_count} individual-identifier mappings")

    conn.close()


if __name__ == "__main__":
    main()
