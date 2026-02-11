"""Load reference tables into SQLite.

Creates: country_continent, regions, individual_viaf tables
Sources: countries_continent.csv, region_code.csv from raw_to_db/
"""

import csv
import os
import sqlite3

from tqdm import tqdm
from utils import get_db_connection, split_wiki

RAW_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "raw_to_db")
WIKIDATA_DIR = os.path.join(RAW_DATA_DIR, "raw_data", "wikidata_data")


def create_tables(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS country_continent (
            country_wikidata_id   TEXT,
            country_name          TEXT,
            continent_wikidata_id TEXT,
            continent_name        TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS regions (
            region_code TEXT PRIMARY KEY,
            region_name TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS individual_viaf (
            wikidata_id TEXT,
            viaf_id     TEXT
        )
    """)
    conn.commit()


def main():
    conn = get_db_connection()
    create_tables(conn)

    conn.execute("DELETE FROM country_continent")
    conn.execute("DELETE FROM regions")
    conn.execute("DELETE FROM individual_viaf")

    # --- Country-Continent mapping ---
    cc_path = os.path.join(WIKIDATA_DIR, "countries_continent.csv")
    if os.path.exists(cc_path):
        import pandas as pd
        df_cc = pd.read_csv(cc_path)

        rows = []
        for _, row in df_cc.iterrows():
            country_id = split_wiki(row.get("country", ""))
            continent_id = split_wiki(row.get("continent", ""))
            rows.append((
                country_id,
                row.get("countryLabel", ""),
                continent_id,
                row.get("continentLabel", ""),
            ))

        conn.executemany("INSERT INTO country_continent VALUES (?, ?, ?, ?)", rows)
        print(f"Loaded {len(rows)} country-continent mappings")
    else:
        print(f"  Warning: {cc_path} not found, skipping country_continent")

    # --- Regions ---
    region_path = os.path.join(RAW_DATA_DIR, "region_code.csv")
    if os.path.exists(region_path):
        import pandas as pd
        df_reg = pd.read_csv(region_path)

        rows = [(row["region_code"], row["region_name"]) for _, row in df_reg.iterrows()]
        conn.executemany("INSERT OR REPLACE INTO regions VALUES (?, ?)", rows)
        print(f"Loaded {len(rows)} regions")
    else:
        print(f"  Warning: {region_path} not found, skipping regions")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
