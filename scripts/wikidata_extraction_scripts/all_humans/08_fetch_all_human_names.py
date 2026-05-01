"""
Fetch all Q5 (human) names/labels using QLever bulk query.
"""

import json
import requests
from tqdm import tqdm

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"

QUERY = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?human ?name WHERE {
  ?human wdt:P31 wd:Q5 .
  ?human rdfs:label ?name .
  FILTER(LANG(?name) = 'en')
}
"""

OUTPUT_FILE = "data/all_humans/all_human_names.json"


def extract_qid(uri: str) -> str:
    if "/Q" in uri:
        return uri.split("/")[-1].rstrip(">")
    return uri


def fetch_all_names():
    print("Querying QLever for all human names (English labels)...")

    params = {
        "query": QUERY,
        "action": "tsv_export"
    }

    response = requests.get(QLEVER_ENDPOINT, params=params, stream=True)
    response.raise_for_status()

    human_names = {}

    lines = response.iter_lines(decode_unicode=True)
    header = next(lines)

    for line in tqdm(lines, desc="Parsing", unit=" rows"):
        if line:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                human_id = extract_qid(parts[0])
                name = parts[1]
                human_names[human_id] = name

    print(f"\nTotal humans with names: {len(human_names):,}")

    with open(OUTPUT_FILE, "w") as f:
        json.dump(human_names, f)

    print(f"Saved to {OUTPUT_FILE}")
    return human_names


if __name__ == "__main__":
    fetch_all_names()
