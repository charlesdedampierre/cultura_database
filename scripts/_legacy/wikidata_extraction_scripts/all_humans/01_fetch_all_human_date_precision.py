"""
Fetch date precision (birthdate & deathdate) for ALL humans using QLever bulk query.

Precision values:
- 11 = day (exact date)
- 10 = month
- 9 = year only
- 8 = decade
- 7 = century

Output: data/all_humans/all_human_date_precision.json
Format: {
  "Q123": {
    "birthdate_precision": 11,
    "deathdate_precision": 9
  },
  ...
}
"""

import json
import requests
from tqdm import tqdm
import time

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"

# Query for birthdate precision
BIRTH_PRECISION_QUERY = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX psv: <http://www.wikidata.org/prop/statement/value/>
PREFIX wikibase: <http://wikiba.se/ontology#>

SELECT ?human ?birthPrecision WHERE {
  ?human wdt:P31 wd:Q5 .
  ?human p:P569 ?birthStmt .
  ?birthStmt psv:P569 ?birthVal .
  ?birthVal wikibase:timePrecision ?birthPrecision .
}
"""

# Query for deathdate precision
DEATH_PRECISION_QUERY = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX psv: <http://www.wikidata.org/prop/statement/value/>
PREFIX wikibase: <http://wikiba.se/ontology#>

SELECT ?human ?deathPrecision WHERE {
  ?human wdt:P31 wd:Q5 .
  ?human p:P570 ?deathStmt .
  ?deathStmt psv:P570 ?deathVal .
  ?deathVal wikibase:timePrecision ?deathPrecision .
}
"""

OUTPUT_FILE = "data/all_humans/all_human_date_precision.json"
BIRTH_OUTPUT = "data/all_humans/all_human_birthdate_precision.json"
DEATH_OUTPUT = "data/all_humans/all_human_deathdate_precision.json"


def extract_qid(uri: str) -> str:
    """Extract Q-id from full URI."""
    if "/Q" in uri:
        return uri.split("/")[-1].rstrip(">")
    return uri


def fetch_precision(query: str, description: str) -> dict:
    """Fetch precision values using bulk query."""
    print(f"Querying QLever for {description}...")

    params = {
        "query": query,
        "action": "tsv_export"
    }

    response = requests.get(QLEVER_ENDPOINT, params=params, stream=True, timeout=600)
    response.raise_for_status()

    precision_data = {}

    lines = response.iter_lines(decode_unicode=True)
    header = next(lines)

    for line in tqdm(lines, desc=f"Parsing {description}", unit=" rows"):
        if line:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                human_id = extract_qid(parts[0])
                try:
                    precision = int(float(parts[1]))
                    # If multiple precision values exist, keep the highest (most precise)
                    if human_id not in precision_data or precision > precision_data[human_id]:
                        precision_data[human_id] = precision
                except (ValueError, TypeError):
                    pass

    print(f"Total humans with {description}: {len(precision_data):,}")
    return precision_data


def main():
    start_time = time.time()

    # Fetch birthdate precision
    print("=" * 60)
    print("STEP 1: Fetching birthdate precision")
    print("=" * 60)
    birth_precision = fetch_precision(BIRTH_PRECISION_QUERY, "birthdate precision")

    # Save intermediate result
    with open(BIRTH_OUTPUT, "w") as f:
        json.dump(birth_precision, f)
    print(f"Saved birthdate precision to {BIRTH_OUTPUT}")

    # Fetch deathdate precision
    print("\n" + "=" * 60)
    print("STEP 2: Fetching deathdate precision")
    print("=" * 60)
    death_precision = fetch_precision(DEATH_PRECISION_QUERY, "deathdate precision")

    # Save intermediate result
    with open(DEATH_OUTPUT, "w") as f:
        json.dump(death_precision, f)
    print(f"Saved deathdate precision to {DEATH_OUTPUT}")

    # Combine results
    print("\n" + "=" * 60)
    print("STEP 3: Combining results")
    print("=" * 60)

    all_ids = set(birth_precision.keys()) | set(death_precision.keys())
    print(f"Total unique humans with date precision: {len(all_ids):,}")

    combined = {}
    for qid in tqdm(all_ids, desc="Combining"):
        combined[qid] = {
            "birthdate_precision": birth_precision.get(qid),
            "deathdate_precision": death_precision.get(qid)
        }

    # Save combined result
    with open(OUTPUT_FILE, "w") as f:
        json.dump(combined, f)

    elapsed = time.time() - start_time

    print("\n" + "=" * 60)
    print("EXTRACTION COMPLETE")
    print("=" * 60)
    print(f"Birthdate precision: {len(birth_precision):,} humans")
    print(f"Deathdate precision: {len(death_precision):,} humans")
    print(f"Combined output: {len(combined):,} humans")
    print(f"Time: {elapsed/60:.1f} minutes")
    print(f"Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
