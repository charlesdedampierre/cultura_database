"""For individuals with century-level (precision=7) birthdate in humans_clean,
look at what the cross-verified database records for the same Q-ids.
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

USECOLS = ["wikidata_code", "name", "birth", "birth_min", "birth_max",
           "approx_birth", "birth_estimation", "bigperiod_birth"]

print("[1/3] Loading humans_clean rows with birthdate_precision = 7 (century)...")
conn = sqlite3.connect(HUMANS_DB)
hc = pd.read_sql_query(
    "SELECT wikidata_id, name_en, birthdate, birthdate_precision "
    "FROM individuals WHERE birthdate_precision = 7",
    conn,
)
conn.close()
print(f"  -> {len(hc):,} individuals with century-level birth precision")
target_ids = set(hc["wikidata_id"].astype(str))

print("[2/3] Streaming cross-verified CSV and selecting matching Q-ids...")
chunks = []
with gzip.open(CROSS_CSV, "rt", encoding="latin-1") as fh:
    reader = pd.read_csv(
        fh, usecols=USECOLS,
        dtype={c: "string" for c in USECOLS},
        chunksize=200_000, low_memory=False,
    )
    for chunk in tqdm(reader, desc="chunks"):
        m = chunk["wikidata_code"].isin(target_ids)
        if m.any():
            chunks.append(chunk[m])
cross = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
print(f"  -> {len(cross):,} of those Q-ids appear in cross-verified")

print("[3/3] Joining and inspecting...")
merged = hc.merge(
    cross, left_on="wikidata_id", right_on="wikidata_code", how="inner"
)

# Width of the birth_min/birth_max bound interval
bmin = pd.to_numeric(merged["birth_min"], errors="coerce")
bmax = pd.to_numeric(merged["birth_max"], errors="coerce")
merged["bound_width"] = (bmax - bmin)

print("\n--- approx_birth distribution ---")
print(merged["approx_birth"].value_counts(dropna=False).head(10))

print("\n--- birth_estimation distribution (top 10) ---")
print(merged["birth_estimation"].value_counts(dropna=False).head(10))

print("\n--- bound_width = birth_max - birth_min (top 12) ---")
print(merged["bound_width"].value_counts(dropna=False).head(12).sort_index())
print(f"  median bound width: {merged['bound_width'].median()}")
print(f"  mean   bound width: {merged['bound_width'].mean():.1f}")

print("\n--- bigperiod_birth distribution (top 10) ---")
print(merged["bigperiod_birth"].value_counts(dropna=False).head(10))

print("\n--- 12 example rows ---")
print(merged[["wikidata_id", "name_en", "birthdate", "birth",
              "birth_min", "birth_max", "approx_birth",
              "birth_estimation", "bigperiod_birth"]].head(12).to_string(index=False))
