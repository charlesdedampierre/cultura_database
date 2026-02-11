"""Load birthcity, deathcity, and nationality location data into SQLite.

Reads: individual_info.json, birthcity_details.json, deathcity_details.json, nationality_coords.json
Creates: individual_birthcity, birthcity, individual_deathcity, deathcity,
         individual_nationality tables
"""

import json
import os
import sqlite3

from tqdm import tqdm
from utils import EXTRACTED_DIR, get_db_connection, point_to_coordinates

INDIVIDUALS_DIR = os.path.join(EXTRACTED_DIR, "individuals")


def create_tables(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS individual_birthcity (
            wikidata_id          TEXT,
            birthcity_wikidata_id TEXT,
            birthcity_name       TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS birthcity (
            birthcity_wikidata_id TEXT PRIMARY KEY,
            birthcity_name        TEXT,
            country_wikidata_id   TEXT,
            country_name          TEXT,
            longitude             REAL,
            latitude              REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS individual_deathcity (
            wikidata_id          TEXT,
            deathcity_wikidata_id TEXT,
            deathcity_name       TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS deathcity (
            deathcity_wikidata_id TEXT PRIMARY KEY,
            deathcity_name        TEXT,
            country_wikidata_id   TEXT,
            country_name          TEXT,
            longitude             REAL,
            latitude              REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS individual_nationality (
            wikidata_id          TEXT,
            nationality_wikidata_id TEXT,
            nationality_name     TEXT,
            longitude            REAL,
            latitude             REAL
        )
    """)
    conn.commit()


def main():
    conn = get_db_connection()
    create_tables(conn)

    # Clear existing data
    for table in ["individual_birthcity", "birthcity", "individual_deathcity",
                   "deathcity", "individual_nationality"]:
        conn.execute(f"DELETE FROM {table}")

    # Load individual info
    with open(os.path.join(INDIVIDUALS_DIR, "individual_info.json")) as f:
        individual_info = json.load(f)

    # --- Birthcities ---
    ind_bc_rows = []
    for info in tqdm(individual_info, desc="Individual birthcities"):
        wid = info["wikidata_id"]
        if info.get("birthcities"):
            for bc in info["birthcities"]:
                ind_bc_rows.append((wid, bc["birthcity_wikidata_id"], bc["birthcity_name"]))

    conn.executemany("INSERT INTO individual_birthcity VALUES (?, ?, ?)", ind_bc_rows)

    # Load birthcity details
    bc_details_path = os.path.join(INDIVIDUALS_DIR, "birthcity_details.json")
    if os.path.exists(bc_details_path):
        with open(bc_details_path) as f:
            bc_details = json.load(f)

        bc_rows = []
        for bc in bc_details:
            coords = point_to_coordinates(bc.get("location", ""))
            lon = coords[0] if coords else None
            lat = coords[1] if coords else None
            bc_rows.append((
                bc["birthcity_wikidata_id"],
                bc.get("birthcity_name", ""),
                bc.get("country_wikidata_id"),
                bc.get("country_name", ""),
                lon, lat,
            ))

        conn.executemany("INSERT OR REPLACE INTO birthcity VALUES (?, ?, ?, ?, ?, ?)", bc_rows)

    # --- Deathcities ---
    ind_dc_rows = []
    for info in tqdm(individual_info, desc="Individual deathcities"):
        wid = info["wikidata_id"]
        if info.get("deathcities"):
            for dc in info["deathcities"]:
                ind_dc_rows.append((wid, dc["deathcity_wikidata_id"], dc["deathcity_name"]))

    conn.executemany("INSERT INTO individual_deathcity VALUES (?, ?, ?)", ind_dc_rows)

    # Load deathcity details
    dc_details_path = os.path.join(INDIVIDUALS_DIR, "deathcity_details.json")
    if os.path.exists(dc_details_path):
        with open(dc_details_path) as f:
            dc_details = json.load(f)

        dc_rows = []
        for dc in dc_details:
            coords = point_to_coordinates(dc.get("location", ""))
            lon = coords[0] if coords else None
            lat = coords[1] if coords else None
            dc_rows.append((
                dc["deathcity_wikidata_id"],
                dc.get("deathcity_name", ""),
                dc.get("country_wikidata_id"),
                dc.get("country_name", ""),
                lon, lat,
            ))

        conn.executemany("INSERT OR REPLACE INTO deathcity VALUES (?, ?, ?, ?, ?, ?)", dc_rows)

    # --- Nationalities ---
    # Load nationality coordinates
    nat_coords = {}
    nat_coords_path = os.path.join(INDIVIDUALS_DIR, "nationality_coords.json")
    if os.path.exists(nat_coords_path):
        with open(nat_coords_path) as f:
            nat_data = json.load(f)
        for nc in nat_data:
            coords = point_to_coordinates(nc.get("location", ""))
            if coords:
                nat_coords[nc["nationality_wikidata_id"]] = coords

    ind_nat_rows = []
    for info in tqdm(individual_info, desc="Individual nationalities"):
        wid = info["wikidata_id"]
        if info.get("nationalities"):
            for nat in info["nationalities"]:
                nat_id = nat["nationality_wikidata_id"]
                coords = nat_coords.get(nat_id)
                lon = coords[0] if coords else None
                lat = coords[1] if coords else None
                ind_nat_rows.append((wid, nat_id, nat["nationality_name"], lon, lat))

    conn.executemany("INSERT INTO individual_nationality VALUES (?, ?, ?, ?, ?)", ind_nat_rows)

    conn.commit()

    # Report counts
    for table in ["individual_birthcity", "birthcity", "individual_deathcity",
                   "deathcity", "individual_nationality"]:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count} rows")

    conn.close()


if __name__ == "__main__":
    main()
