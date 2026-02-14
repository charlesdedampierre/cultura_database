"""
Fetch all Q5 (human) descriptions using QLever bulk query.
"""

import json
import requests
from tqdm import tqdm

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"

QUERY = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX schema: <http://schema.org/>

SELECT ?human ?description WHERE {
  ?human wdt:P31 wd:Q5 .
  ?human schema:description ?description .
  FILTER(LANG(?description) = 'en')
}
"""

OUTPUT_FILE = "data/all_humans/all_human_descriptions.json"


def extract_qid(uri: str) -> str:
    if "/Q" in uri:
        return uri.split("/")[-1].rstrip(">")
    return uri


def fetch_all_descriptions():
    print("Querying QLever for all human descriptions (English)...")

    params = {
        "query": QUERY,
        "action": "tsv_export"
    }

    response = requests.get(QLEVER_ENDPOINT, params=params, stream=True)
    response.raise_for_status()

    human_descriptions = {}

    lines = response.iter_lines(decode_unicode=True)
    header = next(lines)

    for line in tqdm(lines, desc="Parsing", unit=" rows"):
        if line:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                human_id = extract_qid(parts[0])
                description = parts[1]
                human_descriptions[human_id] = description

    print(f"\nTotal humans with descriptions: {len(human_descriptions):,}")

    with open(OUTPUT_FILE, "w") as f:
        json.dump(human_descriptions, f)

    print(f"Saved to {OUTPUT_FILE}")
    return human_descriptions


if __name__ == "__main__":
    fetch_all_descriptions()
