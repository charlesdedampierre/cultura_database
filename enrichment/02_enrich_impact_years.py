"""Compute impact years for each individual.

Formula: impact_year_start = round_nearest(birthyear + 35 - 25, 10)
         impact_year_end   = round_nearest(birthyear + 35 + 25, 10)

Effectively: birthyear + 10 to birthyear + 60, rounded to nearest 10.

Updates: individuals.impact_year_start, individuals.impact_year_end
"""

import os
import sqlite3
import sys

import pandas as pd
from tqdm import tqdm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "loading"))
from utils import get_db_connection


def round_nearest(x: int, num: int = 10) -> int:
    """Round to nearest multiple of num."""
    return ((x + num // 2) // num) * num


def main():
    conn = get_db_connection()

    # Get individuals with birthyear
    df = pd.read_sql_query(
        "SELECT wikidata_id, birthyear FROM individuals WHERE birthyear IS NOT NULL",
        conn,
    )

    print(f"Computing impact years for {len(df)} individuals...")

    df["impact_year_start"] = df["birthyear"].apply(lambda y: round_nearest(y + 35 - 25, 10))
    df["impact_year_end"] = df["birthyear"].apply(lambda y: round_nearest(y + 35 + 25, 10))

    updates = df[["impact_year_start", "impact_year_end", "wikidata_id"]].values.tolist()

    conn.executemany(
        """UPDATE individuals
           SET impact_year_start = ?, impact_year_end = ?
           WHERE wikidata_id = ?""",
        updates,
    )
    conn.commit()

    count = conn.execute(
        "SELECT COUNT(*) FROM individuals WHERE impact_year_start IS NOT NULL"
    ).fetchone()[0]
    print(f"Updated impact years for {count} individuals")

    conn.close()


if __name__ == "__main__":
    main()
