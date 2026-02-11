"""Apply manual region corrections from Excel and CSV files.

Reads corrections from:
- Golden Age - Individuals Check.xlsx (per-sheet, maps meta_country to region codes)
- ENS - Cultural Index - Countries Databases - individuals_cleaned.csv

Updates: individual_regions table
"""

import os
import sqlite3
import sys

import numpy as np
import pandas as pd
from tqdm import tqdm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "loading"))
from utils import get_db_connection

MANUAL_DIR = os.path.join(
    os.path.dirname(__file__), "..", "archive", "legacy", "raw_to_json",
    "manual_individuals_check",
)

# Map cultural/regional descriptors to standard region codes
ADAPTED_COUNTRY = {
    "Arab Countries": ["re_arabic_world", "re_muslim_world"],
    "Arab World": ["re_arabic_world", "re_muslim_world"],
    "Armenian": ["re_arabic_world", "re_muslim_world"],
    "Danish": ["re_nordic_countries", "re_western_europe", "re_northwestern_europe", "re_denmark"],
    "English": ["re_united_kingdom", "re_western_europe", "re_northwestern_europe"],
    "French": ["re_france", "re_western_europe", "re_southwestern_europe"],
    "Greek ": ["re_greek_world", "re_greece"],
    "Greek World": ["re_greek_world", "re_greece"],
    "Indian Countries": ["re_indian_world"],
    "Italy": ["re_italy", "re_western_europe", "re_southwestern_europe"],
    "Latin World": ["re_latin"],
    "Low Countries": ["re_low_countries", "re_western_europe", "re_northwestern_europe"],
    "Persian World": ["re_persian_world"],
    "Portugal": ["re_portugal", "re_western_europe", "re_southwestern_europe"],
    "Russian": ["re_eastern_europe", "re_slav_world"],
    "Russsian": ["re_eastern_europe", "re_slav_world"],
    "Spain": ["re_spain", "re_western_europe", "re_southwestern_europe"],
    "Spanish": ["re_spain", "re_western_europe", "re_southwestern_europe"],
    "Suisse": ["re_german_world", "re_western_europe", "re_northwestern_europe", "re_switzerland"],
    "Turkish World": ["re_greek_world", "re_ottoman_turkey"],
    "UK": ["re_united_kingdom", "re_western_europe", "re_northwestern_europe"],
}


def load_excel_corrections() -> pd.DataFrame:
    """Load manual corrections from Golden Age Excel file."""
    excel_path = os.path.join(MANUAL_DIR, "Golden Age - Individuals Check.xlsx")
    if not os.path.exists(excel_path):
        print(f"  Warning: {excel_path} not found, skipping")
        return pd.DataFrame(columns=["wikidata_id", "region_code"])

    excel_file = pd.ExcelFile(excel_path)
    all_data = pd.DataFrame()

    for sheet_name in excel_file.sheet_names:
        df = pd.read_excel(excel_file, sheet_name=sheet_name)
        all_data = pd.concat([all_data, df], ignore_index=True)

    df_old = all_data[["individual_id", "meta_country", "new_meta_country"]].copy()
    df_old = df_old.rename(columns={"individual_id": "wikidata_id"})
    df_old = df_old.dropna().reset_index(drop=True)

    df_old["region_code"] = df_old["new_meta_country"].apply(
        lambda x: ADAPTED_COUNTRY.get(x)
    )
    df_old = df_old.drop(["meta_country", "new_meta_country"], axis=1)
    df_old = df_old.explode("region_code")
    df_old = df_old.dropna().drop_duplicates().reset_index(drop=True)

    return df_old


def load_csv_corrections() -> pd.DataFrame:
    """Load manual corrections from CSV file."""
    csv_path = os.path.join(
        MANUAL_DIR, "ENS - Cultural Index - Countries Databases - individuals_cleaned.csv"
    )
    if not os.path.exists(csv_path):
        print(f"  Warning: {csv_path} not found, skipping")
        return pd.DataFrame(columns=["wikidata_id", "region_code"])

    df = pd.read_csv(csv_path)
    df = df[["wikidata_id", "region_code_corrected"]].dropna()
    df = df.rename(columns={"region_code_corrected": "region_code"})

    # Split comma-separated region codes
    df["region_code"] = df["region_code"].apply(lambda x: str(x).split(","))
    df = df.explode("region_code")
    df["region_code"] = df["region_code"].str.strip()
    df = df[df["region_code"] != "None"]
    df = df.drop_duplicates().reset_index(drop=True)

    return df


def main():
    conn = get_db_connection()

    # Load existing regions
    df_existing = pd.read_sql_query(
        "SELECT wikidata_id, region_code FROM individual_regions", conn
    )

    # Load corrections
    df_excel = load_excel_corrections()
    df_csv = load_csv_corrections()

    print(f"Excel corrections: {df_excel['wikidata_id'].nunique()} individuals")
    print(f"CSV corrections: {df_csv['wikidata_id'].nunique()} individuals")

    # Get IDs that need replacement
    corrected_ids = set(df_excel["wikidata_id"]) | set(df_csv["wikidata_id"])

    # Remove existing regions for corrected individuals
    df_unchanged = df_existing[~df_existing["wikidata_id"].isin(corrected_ids)]

    # For CSV corrections, they override everything (including Excel)
    csv_ids = set(df_csv["wikidata_id"])
    df_excel_final = df_excel[~df_excel["wikidata_id"].isin(csv_ids)]

    # Combine: unchanged + excel corrections + csv corrections
    final = pd.concat([df_unchanged, df_excel_final, df_csv])
    final = final.drop_duplicates().reset_index(drop=True)

    # Remove "None" values
    final = final[final["region_code"].notna()]
    final = final[final["region_code"] != "None"]

    # Rewrite table
    conn.execute("DELETE FROM individual_regions")
    rows = final.values.tolist()
    conn.executemany("INSERT INTO individual_regions VALUES (?, ?)", rows)
    conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM individual_regions").fetchone()[0]
    unique = conn.execute("SELECT COUNT(DISTINCT wikidata_id) FROM individual_regions").fetchone()[0]
    print(f"After manual corrections: {count} region assignments for {unique} individuals")

    conn.close()


if __name__ == "__main__":
    main()
