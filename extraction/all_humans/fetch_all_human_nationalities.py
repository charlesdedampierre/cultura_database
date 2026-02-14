"""
Fetch all Q5 (human) nationalities (P27 - country of citizenship) with English labels using QLever bulk query.
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

SELECT ?human ?nationality ?nationalityLabel WHERE {
  ?human wdt:P31 wd:Q5 .
  ?human wdt:P27 ?nationality .
  ?nationality rdfs:label ?nationalityLabel .
  FILTER(LANG(?nationalityLabel) = 'en')
}
"""

OUTPUT_FILE = "data/all_humans/all_human_nationalities.json"


def extract_qid(uri: str) -> str:
    if "/Q" in uri:
        return uri.split("/")[-1].rstrip(">")
    return uri


def fetch_all_nationalities():
    print("Querying QLever for all human nationalities (P27) with English labels...")

    params = {
        "query": QUERY,
        "action": "tsv_export"
    }

    response = requests.get(QLEVER_ENDPOINT, params=params, stream=True)
    response.raise_for_status()

    # Store as dict: human_id -> list of {"id": nat_id, "name": nat_label}
    human_nationalities = defaultdict(list)

    lines = response.iter_lines(decode_unicode=True)
    header = next(lines)

    for line in tqdm(lines, desc="Parsing", unit=" rows"):
        if line:
            parts = line.strip().split("\t")
            if len(parts) >= 3:
                human_id = extract_qid(parts[0])
                nat_id = extract_qid(parts[1])
                nat_label = parts[2]
                human_nationalities[human_id].append({"id": nat_id, "name": nat_label})

    print(f"\nTotal humans with nationalities: {len(human_nationalities):,}")
    total_pairs = sum(len(nats) for nats in human_nationalities.values())
    print(f"Total nationality assignments: {total_pairs:,}")

    with open(OUTPUT_FILE, "w") as f:
        json.dump(dict(human_nationalities), f)

    print(f"Saved to {OUTPUT_FILE}")
    return human_nationalities


if __name__ == "__main__":
    fetch_all_nationalities()
