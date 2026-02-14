"""
Fetch all Q5 (human) deathdates (P570) using QLever bulk query.
"""

import json
import requests
from tqdm import tqdm

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"

QUERY = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?human ?deathdate WHERE {
  ?human wdt:P31 wd:Q5 .
  ?human wdt:P570 ?deathdate .
}
"""

OUTPUT_FILE = "data/all_humans/all_human_deathdates.json"


def extract_qid(uri: str) -> str:
    if "/Q" in uri:
        return uri.split("/")[-1].rstrip(">")
    return uri


def fetch_all_deathdates():
    print("Querying QLever for all human deathdates (P570)...")

    params = {
        "query": QUERY,
        "action": "tsv_export"
    }

    response = requests.get(QLEVER_ENDPOINT, params=params, stream=True)
    response.raise_for_status()

    human_deathdates = {}

    lines = response.iter_lines(decode_unicode=True)
    header = next(lines)

    for line in tqdm(lines, desc="Parsing", unit=" rows"):
        if line:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                human_id = extract_qid(parts[0])
                deathdate = parts[1]
                human_deathdates[human_id] = deathdate

    print(f"\nTotal humans with deathdates: {len(human_deathdates):,}")

    with open(OUTPUT_FILE, "w") as f:
        json.dump(human_deathdates, f)

    print(f"Saved to {OUTPUT_FILE}")
    return human_deathdates


if __name__ == "__main__":
    fetch_all_deathdates()
