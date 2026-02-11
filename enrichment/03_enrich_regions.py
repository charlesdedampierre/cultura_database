"""Assign regions to individuals based on country + time + optional spatial bounds.

Reads the region consolidation CSV and matches individuals to regions based on:
- Non-space-based regions: country ISO code + temporal overlap with impact years
- Space-based regions: additionally checks if birthcity coordinates fall within
  the region's bounding box (min/max latitude/longitude)

Creates/populates: individual_regions table
"""

import math
import os
import sqlite3
import sys
import warnings

import pandas as pd
from tqdm import tqdm

tqdm.pandas()
warnings.filterwarnings("ignore", category=FutureWarning)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "loading"))
from utils import get_db_connection

# Region consolidation table
REGION_CSV = os.path.join(
    os.path.dirname(__file__), "..", "archive", "legacy", "raw_to_json",
    "ENS - Cultural Index - Countries Databases - consolidate_table.csv",
)


def create_tables(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS individual_regions (
            wikidata_id TEXT,
            region_code TEXT
        )
    """)
    conn.commit()


def filter_space(row) -> int:
    """Check if a point falls within a bounding box."""
    if (
        row["latitude"] <= row["max_latitude"]
        and row["latitude"] >= row["min_latitude"]
        and row["longitude"] <= row["max_longitude"]
        and row["longitude"] >= row["min_longitude"]
    ):
        return 1
    return 0


def main():
    conn = get_db_connection()
    create_tables(conn)
    conn.execute("DELETE FROM individual_regions")

    # Load region definitions
    df_reg_all = pd.read_csv(REGION_CSV)

    # Load individuals with country + impact years
    df_ind = pd.read_sql_query(
        """SELECT wikidata_id AS wiki_id, country_code AS iso_a3,
                  impact_year_start, impact_year_end
           FROM individuals
           WHERE country_code IS NOT NULL AND impact_year_start IS NOT NULL""",
        conn,
    )

    # Expand impact years into 10-year steps
    df_ind["impact_year"] = df_ind.apply(
        lambda row: list(range(int(row["impact_year_start"]),
                               int(row["impact_year_end"]) + 10, 10)),
        axis=1,
    )
    df_ind = df_ind.explode("impact_year").reset_index(drop=True)
    df_ind = df_ind.drop(["impact_year_start", "impact_year_end"], axis=1)

    # --- Non-space-based regions ---
    df_reg_non_space = df_reg_all[df_reg_all["space_based"] == 0].copy()

    # Expand region time ranges
    df_reg_non_space["impact_year"] = df_reg_non_space.apply(
        lambda row: list(range(int(row["min_date"]), int(row["max_date"]) + 10, 10)),
        axis=1,
    )
    df_reg_non_space = df_reg_non_space.explode("impact_year").reset_index(drop=True)

    # Match on iso_a3 + impact_year
    final_non_space = pd.merge(
        df_ind, df_reg_non_space, on=["iso_a3", "impact_year"]
    )
    final_non_space = (
        final_non_space[["wiki_id", "region_code"]]
        .drop_duplicates()
        .reset_index(drop=True)
    )
    print(f"Non-space region matches: {len(final_non_space)}")

    # --- Space-based regions ---
    # Load birthcity coordinates for individuals
    df_bc = pd.read_sql_query(
        """SELECT ib.wikidata_id AS wiki_id, bc.longitude, bc.latitude
           FROM individual_birthcity ib
           JOIN birthcity bc ON ib.birthcity_wikidata_id = bc.birthcity_wikidata_id
           WHERE bc.longitude IS NOT NULL AND bc.latitude IS NOT NULL""",
        conn,
    )

    if not df_bc.empty:
        # Merge with individual data
        df_ind_space = pd.merge(df_ind, df_bc, on="wiki_id")
        df_ind_space = df_ind_space.drop_duplicates()

        df_reg_space = df_reg_all[df_reg_all["space_based"] == 1].copy()
        df_reg_space["impact_year"] = df_reg_space.apply(
            lambda row: list(range(int(row["min_date"]), int(row["max_date"]) + 10, 10)),
            axis=1,
        )
        df_reg_space = df_reg_space.explode("impact_year").reset_index(drop=True)

        final_space = pd.merge(
            df_reg_space, df_ind_space, on=["iso_a3", "impact_year"]
        )

        # Fill NaN bounding boxes with global bounds
        final_space["min_latitude"] = final_space["min_latitude"].fillna(-90)
        final_space["max_latitude"] = final_space["max_latitude"].fillna(90)
        final_space["min_longitude"] = final_space["min_longitude"].fillna(-180)
        final_space["max_longitude"] = final_space["max_longitude"].fillna(180)
        final_space["latitude"] = final_space["latitude"].astype(float)
        final_space["longitude"] = final_space["longitude"].astype(float)

        print("Checking spatial bounds...")
        final_space["criteria"] = final_space.progress_apply(filter_space, axis=1)
        final_space = final_space[final_space["criteria"] == 1].reset_index(drop=True)
        final_space = (
            final_space[["wiki_id", "region_code"]]
            .drop_duplicates()
            .reset_index(drop=True)
        )
        print(f"Space region matches: {len(final_space)}")
    else:
        final_space = pd.DataFrame(columns=["wiki_id", "region_code"])
        print("No birthcity coordinates available for space-based matching")

    # Combine
    final = pd.concat([final_non_space, final_space]).drop_duplicates().reset_index(drop=True)
    print(f"Total individual-region assignments: {len(final)}")

    # Insert into database
    rows = final.rename(columns={"wiki_id": "wikidata_id"}).values.tolist()
    conn.executemany("INSERT INTO individual_regions VALUES (?, ?)", rows)
    conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM individual_regions").fetchone()[0]
    unique = conn.execute("SELECT COUNT(DISTINCT wikidata_id) FROM individual_regions").fetchone()[0]
    print(f"Loaded {count} region assignments for {unique} individuals")

    conn.close()


if __name__ == "__main__":
    main()
