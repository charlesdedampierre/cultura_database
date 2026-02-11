"""Load individuals and gender data into SQLite.

Reads: individuals.json, individual_info.json
Creates: individuals, individual_gender tables
"""

import json
import os
import sqlite3

from tqdm import tqdm
from utils import EXTRACTED_DIR, clean_date, get_db_connection

INDIVIDUALS_DIR = os.path.join(EXTRACTED_DIR, "individuals")


def create_tables(conn: sqlite3.Connection):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS individuals (
            wikidata_id         TEXT PRIMARY KEY,
            name                TEXT,
            birthyear           INTEGER,
            country_code        TEXT,
            country_name        TEXT,
            country_data_origin TEXT,
            impact_year_start   INTEGER,
            impact_year_end     INTEGER,
            identifier_count    INTEGER DEFAULT 0
        )
    """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS individual_gender (
            wikidata_id TEXT,
            gender      TEXT
        )
    """
    )
    conn.commit()


def main():
    conn = get_db_connection()
    create_tables(conn)

    # Clear existing data
    conn.execute("DELETE FROM individuals")
    conn.execute("DELETE FROM individual_gender")

    # Load individuals
    with open(os.path.join(INDIVIDUALS_DIR, "individuals.json")) as f:
        individuals = json.load(f)

    # Load individual info for birthyear and gender
    with open(os.path.join(INDIVIDUALS_DIR, "individual_info.json")) as f:
        individual_info = json.load(f)

    # Build info lookup
    info_by_id = {info["wikidata_id"]: info for info in individual_info}

    # Insert individuals
    ind_rows = []
    gender_rows = []

    for ind in tqdm(individuals, desc="Loading individuals"):
        wid = ind["wikidata_id"]
        name = ind.get("name", "")
        info = info_by_id.get(wid, {})
        birthyear = clean_date(info.get("birthdate"))

        ind_rows.append((wid, name, birthyear))

        # Gender
        genders = info.get("gender")
        if genders:
            for g in genders:
                gender_rows.append((wid, g))

    conn.executemany(
        "INSERT OR REPLACE INTO individuals (wikidata_id, name, birthyear) VALUES (?, ?, ?)",
        ind_rows,
    )
    conn.executemany(
        "INSERT INTO individual_gender (wikidata_id, gender) VALUES (?, ?)",
        gender_rows,
    )
    conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]
    gender_count = conn.execute("SELECT COUNT(*) FROM individual_gender").fetchone()[0]
    print(f"Loaded {count} individuals, {gender_count} gender records")

    conn.close()


if __name__ == "__main__":
    main()
