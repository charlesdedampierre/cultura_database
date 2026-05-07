"""Extract the level3 -> level2 -> level1 occupation mapping from the
cross-verified-database CSV.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pandas as pd
from tqdm import tqdm

ROOT = Path("/Users/charlesdedampierre/Desktop/Rsearch Folder/cultura_database")
CROSS_CSV = (ROOT / "data/similar_databases/cross-verified-database/"
             "cross-verified-database.csv.gz")
OUT_DIR = ROOT / "data/similar_databases/cross-verified-database"
OUT_FULL = OUT_DIR / "occupation_hierarchy.csv"
OUT_L2 = OUT_DIR / "occupation_level2_to_level1.csv"
OUT_L3 = OUT_DIR / "occupation_level3_to_level2.csv"

USECOLS = ["level1_main_occ", "level2_main_occ", "level3_main_occ"]

print("Streaming CSV and aggregating occupation triples...")
counts: dict[tuple[str, str, str], int] = {}
with gzip.open(CROSS_CSV, "rt", encoding="latin-1") as fh:
    reader = pd.read_csv(
        fh, usecols=USECOLS,
        dtype={c: "string" for c in USECOLS},
        chunksize=200_000, low_memory=False,
    )
    for chunk in tqdm(reader, desc="chunks"):
        chunk = chunk.fillna("")
        g = chunk.groupby(USECOLS, dropna=False).size()
        for key, n in g.items():
            counts[key] = counts.get(key, 0) + int(n)

triples = (
    pd.DataFrame(
        [(*k, v) for k, v in counts.items()],
        columns=["level1_main_occ", "level2_main_occ",
                 "level3_main_occ", "n_individuals"],
    )
    .sort_values(["level1_main_occ", "level2_main_occ",
                  "level3_main_occ"])
    .reset_index(drop=True)
)
print(f"  -> {len(triples):,} unique (L1,L2,L3) triples")
triples.to_csv(OUT_FULL, index=False)
print(f"  wrote {OUT_FULL.relative_to(ROOT)}")

# Pivot to a clean L3 -> L2 mapping (taking the dominant L2 per L3)
l3_to_l2 = (
    triples.groupby(["level3_main_occ", "level2_main_occ"], as_index=False)
    ["n_individuals"].sum()
    .sort_values(["level3_main_occ", "n_individuals"], ascending=[True, False])
    .drop_duplicates("level3_main_occ", keep="first")
    .rename(columns={"n_individuals": "n"})
)
print(f"  -> {len(l3_to_l2):,} unique level3 occupations "
      f"(mapped to dominant level2)")
l3_to_l2.to_csv(OUT_L3, index=False)
print(f"  wrote {OUT_L3.relative_to(ROOT)}")

# L2 -> L1
l2_to_l1 = (
    triples.groupby(["level2_main_occ", "level1_main_occ"], as_index=False)
    ["n_individuals"].sum()
    .sort_values(["level2_main_occ", "n_individuals"], ascending=[True, False])
    .drop_duplicates("level2_main_occ", keep="first")
    .rename(columns={"n_individuals": "n"})
)
print(f"  -> {len(l2_to_l1):,} unique level2 occupations "
      f"(mapped to level1)")
l2_to_l1.to_csv(OUT_L2, index=False)
print(f"  wrote {OUT_L2.relative_to(ROOT)}")

print("\n--- LEVEL 1 -> LEVEL 2 hierarchy ---")
overview = (
    triples.groupby(["level1_main_occ", "level2_main_occ"], as_index=False)
    ["n_individuals"].sum()
    .sort_values(["level1_main_occ", "n_individuals"],
                 ascending=[True, False])
)
for l1, sub in overview.groupby("level1_main_occ"):
    print(f"\n[{l1 or '<empty>'}]   total={sub['n_individuals'].sum():,}")
    for _, row in sub.iterrows():
        print(f"   - {row['level2_main_occ'] or '<empty>':<40} "
              f"{row['n_individuals']:>10,}")

print("\n--- 12 most frequent level3 occupations ---")
top_l3 = (
    triples.groupby("level3_main_occ", as_index=False)["n_individuals"]
    .sum().sort_values("n_individuals", ascending=False).head(12)
    .merge(l3_to_l2[["level3_main_occ", "level2_main_occ"]],
           on="level3_main_occ", how="left")
    .merge(l2_to_l1[["level2_main_occ", "level1_main_occ"]],
           on="level2_main_occ", how="left")
)
print(top_l3.to_string(index=False))
