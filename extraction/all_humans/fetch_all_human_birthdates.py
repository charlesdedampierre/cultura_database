"""
Fetch all Q5 (human) birthdates (P569) using QLever bulk query.
"""

import json
import requests
from tqdm import tqdm

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"

QUERY = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?human ?birthdate WHERE {
  ?human wdt:P31 wd:Q5 .
  ?human wdt:P569 ?birthdate .
}
"""

OUTPUT_FILE = "data/all_humans/all_human_birthdates.json"


def extract_qid(uri: str) -> str:
    if "/Q" in uri:
        return uri.split("/")[-1].rstrip(">")
    return uri


def fetch_all_birthdates():
    print("Querying QLever for all human birthdates (P569)...")

    params = {
        "query": QUERY,
        "action": "tsv_export"
    }

    response = requests.get(QLEVER_ENDPOINT, params=params, stream=True)
    response.raise_for_status()

    human_birthdates = {}

    lines = response.iter_lines(decode_unicode=True)
    header = next(lines)

    for line in tqdm(lines, desc="Parsing", unit=" rows"):
        if line:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                human_id = extract_qid(parts[0])
                birthdate = parts[1]
                human_birthdates[human_id] = birthdate

    print(f"\nTotal humans with birthdates: {len(human_birthdates):,}")

    with open(OUTPUT_FILE, "w") as f:
        json.dump(human_birthdates, f)

    print(f"Saved to {OUTPUT_FILE}")
    return human_birthdates


if __name__ == "__main__":
    fetch_all_birthdates()
