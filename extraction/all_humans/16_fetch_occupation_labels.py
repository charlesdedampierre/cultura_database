"""
Fetch labels for all unique occupations found in humans.
"""

import json
import requests
from tqdm import tqdm

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"

INPUT_FILE = "data/all_humans/all_human_occupations.json"
OUTPUT_FILE = "data/all_humans/occupation_labels.json"

QUERY = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?occupation ?label WHERE {
  ?human wdt:P31 wd:Q5 .
  ?human wdt:P106 ?occupation .
  ?occupation rdfs:label ?label .
  FILTER(LANG(?label) = 'en')
}
"""


def fetch_occupation_labels():
    print("Querying QLever for occupation labels...")

    params = {
        "query": QUERY,
        "action": "tsv_export"
    }

    response = requests.get(QLEVER_ENDPOINT, params=params, stream=True)
    response.raise_for_status()

    occupation_labels = {}

    lines = response.iter_lines(decode_unicode=True)
    header = next(lines)

    for line in tqdm(lines, desc="Parsing", unit=" rows"):
        if line:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                uri = parts[0]
                label = parts[1]
                if "/Q" in uri:
                    qid = uri.split("/")[-1].rstrip(">")
                    occupation_labels[qid] = label

    print(f"\nUnique occupations with labels: {len(occupation_labels):,}")

    with open(OUTPUT_FILE, "w") as f:
        json.dump(occupation_labels, f, indent=2)

    print(f"Saved to {OUTPUT_FILE}")

    # Show some examples
    print("\nExamples:")
    for qid, label in list(occupation_labels.items())[:10]:
        print(f"  {qid}: {label}")

    return occupation_labels


if __name__ == "__main__":
    fetch_occupation_labels()
