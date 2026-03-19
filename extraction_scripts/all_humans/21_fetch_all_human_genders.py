"""
Fetch all Q5 (human) gender/sex (P21 - sex or gender) with English labels using QLever bulk query.
"""

import json
import requests
from tqdm import tqdm
from collections import defaultdict

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"

QUERY = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?human ?gender ?genderLabel WHERE {
  ?human wdt:P31 wd:Q5 .
  ?human wdt:P21 ?gender .
  ?gender rdfs:label ?genderLabel .
  FILTER(LANG(?genderLabel) = 'en')
}
"""

OUTPUT_FILE = "data/all_humans/all_human_genders.json"


def extract_qid(uri: str) -> str:
    if "/Q" in uri:
        return uri.split("/")[-1].rstrip(">")
    return uri


def fetch_all_genders():
    print("Querying QLever for all human genders (P21) with English labels...")

    params = {
        "query": QUERY,
        "action": "tsv_export"
    }

    response = requests.get(QLEVER_ENDPOINT, params=params, stream=True)
    response.raise_for_status()

    # Store as dict: human_id -> {"id": gender_id, "name": gender_label}
    # Most humans have a single gender, but we'll use the first one if multiple
    human_genders = {}

    lines = response.iter_lines(decode_unicode=True)
    header = next(lines)

    for line in tqdm(lines, desc="Parsing", unit=" rows"):
        if line:
            parts = line.strip().split("\t")
            if len(parts) >= 3:
                human_id = extract_qid(parts[0])
                gender_id = extract_qid(parts[1])
                gender_label = parts[2]
                # Keep first gender encountered (most will have only one)
                if human_id not in human_genders:
                    human_genders[human_id] = {"id": gender_id, "name": gender_label}

    print(f"\nTotal humans with gender: {len(human_genders):,}")

    # Show distribution of genders
    gender_counts = defaultdict(int)
    for g in human_genders.values():
        gender_counts[g["name"]] += 1

    print("\nGender distribution:")
    for gender, count in sorted(gender_counts.items(), key=lambda x: -x[1]):
        print(f"  {gender}: {count:,}")

    with open(OUTPUT_FILE, "w") as f:
        json.dump(human_genders, f)

    print(f"\nSaved to {OUTPUT_FILE}")
    return human_genders


if __name__ == "__main__":
    fetch_all_genders()
