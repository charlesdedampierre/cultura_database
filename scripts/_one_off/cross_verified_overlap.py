"""Compare the cross-verified human database against humans_clean.

Computes:
  1) Cross-verified Q-ids that are absent from humans_clean.individuals
     (treated as the "non-human / discarded" set).
  2) Among cross-verified individuals that have BOTH a birthdate AND a
     country of citizenship in the cross-verified file, how many lack
     a floruit, a polity, or both in humans_clean.
"""

from __future__ import annotations

import gzip
import sqlite3
from pathlib import Path

import pandas as pd
from tqdm import tqdm

ROOT = Path("/Users/charlesdedampierre/Desktop/Rsearch Folder/cultura_database")
CROSS_CSV = ROOT / "data/cross-verified-database/cross-verified-database.csv.gz"
HUMANS_DB = ROOT / "data/humans_clean.sqlite3"

USECOLS = ["wikidata_code", "birth", "citizenship_1_b"]


def load_cross_verified() -> pd.DataFrame:
    print("[1/4] Loading cross-verified-database.csv.gz (chunked)...")
    chunks = []
    with gzip.open(CROSS_CSV, "rt", encoding="latin-1") as fh:
        reader = pd.read_csv(
            fh,
            usecols=USECOLS,
            dtype={"wikidata_code": "string",
                   "birth": "string",
                   "citizenship_1_b": "string"},
            chunksize=200_000,
            low_memory=False,
        )
        for chunk in tqdm(reader, desc="reading CSV chunks"):
            chunks.append(chunk)
    df = pd.concat(chunks, ignore_index=True)
    print(f"  -> {len(df):,} rows in cross-verified")
    return df


def load_humans_clean() -> tuple[set[str], set[str], set[str]]:
    print("[2/4] Loading humans_clean tables...")
    conn = sqlite3.connect(HUMANS_DB)
    try:
        all_ids = pd.read_sql_query(
            "SELECT wikidata_id FROM individuals", conn
        )["wikidata_id"].astype("string")

        floruit_ids = pd.read_sql_query(
            "SELECT wikidata_id FROM individuals_floruit_period "
            "WHERE floruit_period IS NOT NULL AND floruit_period != ''",
            conn,
        )["wikidata_id"].astype("string")

        polity_ids = pd.read_sql_query(
            "SELECT DISTINCT wikidata_id FROM individuals_cliopatria "
            "WHERE polity_id IS NOT NULL AND polity_id != ''",
            conn,
        )["wikidata_id"].astype("string")
    finally:
        conn.close()

    print(f"  -> humans_clean rows: {len(all_ids):,}")
    print(f"  -> with floruit:      {len(floruit_ids):,}")
    print(f"  -> with polity:       {len(polity_ids):,}")
    return set(all_ids), set(floruit_ids), set(polity_ids)


def main() -> None:
    cross = load_cross_verified()
    hc_ids, floruit_ids, polity_ids = load_humans_clean()

    print("[3/4] Identifying cross-verified rows missing from humans_clean...")
    cross_qids = cross["wikidata_code"].dropna()
    in_hc_mask = cross_qids.isin(hc_ids)
    n_total = len(cross_qids)
    n_missing = (~in_hc_mask).sum()
    print(f"  -> cross-verified Q-ids:                {n_total:,}")
    print(f"  -> NOT present in humans_clean (discarded / non-human): "
          f"{n_missing:,}")

    print("[4/4] Restricting to cross-verified rows with birthdate AND "
          "citizenship_1_b ...")
    has_birth = cross["birth"].notna() & (cross["birth"].str.strip() != "")
    has_cit = (cross["citizenship_1_b"].notna()
               & (cross["citizenship_1_b"].str.strip() != ""))
    sub = cross[has_birth & has_cit].copy()
    print(f"  -> cross-verified rows with birth & citizenship: "
          f"{len(sub):,}")

    sub_qids = sub["wikidata_code"].dropna()
    in_hc = sub_qids.isin(hc_ids)
    sub_in_hc = sub_qids[in_hc]
    print(f"     of which present in humans_clean:             "
          f"{len(sub_in_hc):,}")
    print(f"     of which NOT present in humans_clean:         "
          f"{(~in_hc).sum():,}")

    has_floruit = sub_in_hc.isin(floruit_ids)
    has_polity = sub_in_hc.isin(polity_ids)

    n_no_floruit = (~has_floruit).sum()
    n_no_polity = (~has_polity).sum()
    n_no_either = (~(has_floruit | has_polity)).sum()      # neither
    n_missing_one = (~(has_floruit & has_polity)).sum()    # at least one missing

    print("\n=== RESULTS ===")
    print(f"Cross-verified individuals (total):                "
          f"{n_total:,}")
    print(f"  NOT in humans_clean (discarded / non-human):     "
          f"{n_missing:,}")
    print(f"\nCross-verified with birthdate AND citizenship:    "
          f"{len(sub):,}")
    print(f"  present in humans_clean:                         "
          f"{len(sub_in_hc):,}")
    print(f"    of those, missing floruit in humans_clean:     "
          f"{n_no_floruit:,}")
    print(f"    of those, missing polity in humans_clean:      "
          f"{n_no_polity:,}")
    print(f"    of those, missing BOTH (no floruit & no polity):"
          f" {n_no_either:,}")
    print(f"    of those, missing AT LEAST ONE:                 "
          f"{n_missing_one:,}")


if __name__ == "__main__":
    main()
