"""Convert the Cross-Verified database CSV to a slim parquet for the country explorer app.

Keeps only the columns useful for browsing individuals by country of citizenship,
and writes one parquet partitioned by `citizenship_1_b` for fast country lookups.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "similar_databases" / "cross-verified-database" / "cross-verified-database.utf8.csv.gz"
OUT = ROOT / "data" / "cv_country_explorer.parquet"

KEEP_COLS = [
    "wikidata_code",
    "name",
    "gender",
    "birth",
    "death",
    "citizenship_1_b",
    "citizenship_2_b",
    "string_citizenship_raw_d",
    "level1_main_occ",
    "level2_main_occ",
    "level3_main_occ",
    "level3_all_occ",
    "un_region",
    "un_subregion",
    "bigperiod_birth",
    "bigperiod_death",
    "wiki_readers_2015_2018",
    "number_wiki_editions",
    "ranking_visib_5criteria",
    "sum_visib_ln_5criteria",
    "bplo1",
    "bpla1",
    "dplo1",
    "dpla1",
    "curid",
]


def main() -> None:
    chunks: list[pd.DataFrame] = []
    reader = pd.read_csv(SRC, usecols=KEEP_COLS, chunksize=200_000, low_memory=False)
    for chunk in tqdm(reader, desc="Reading CV CSV", unit="chunk"):
        chunks.append(chunk)
    df = pd.concat(chunks, ignore_index=True)
    print(f"Loaded {len(df):,} rows")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    print(f"Wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
