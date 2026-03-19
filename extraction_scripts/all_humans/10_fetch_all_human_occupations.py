"""
Fetch all Q5 (human) occupations using QLever bulk query.
Returns pairs of (human_id, occupation_id).
"""

import json
import requests
from tqdm import tqdm
from collections import defaultdict

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"

QUERY = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?human ?occupation WHERE {
  ?human wdt:P31 wd:Q5 .
  ?human wdt:P106 ?occupation .
}
"""

OUTPUT_FILE = "data/all_humans/all_human_occupations.json"


def extract_qid(uri: str) -> str:
    """Extract Q-id from full URI."""
    if "/Q" in uri:
        return uri.split("/")[-1].rstrip(">")
    return uri


def fetch_all_occupations():
    print("Querying QLever for all human occupations (P106)...")

    params = {
        "query": QUERY,
        "action": "tsv_export"
    }

    response = requests.get(QLEVER_ENDPOINT, params=params, stream=True)
    response.raise_for_status()

    # Store as dict: human_id -> list of occupation_ids
    human_occupations = defaultdict(list)

    lines = response.iter_lines(decode_unicode=True)
    header = next(lines)  # Skip header

    for line in tqdm(lines, desc="Parsing results", unit=" pairs"):
        if line:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                human_id = extract_qid(parts[0])
                occupation_id = extract_qid(parts[1])
                human_occupations[human_id].append(occupation_id)

    print(f"\nTotal humans with occupations: {len(human_occupations):,}")
    total_pairs = sum(len(occs) for occs in human_occupations.values())
    print(f"Total occupation assignments: {total_pairs:,}")

    # Save to JSON
    with open(OUTPUT_FILE, "w") as f:
        json.dump(dict(human_occupations), f)

    print(f"Saved to {OUTPUT_FILE}")
    return human_occupations


if __name__ == "__main__":
    fetch_all_occupations()
