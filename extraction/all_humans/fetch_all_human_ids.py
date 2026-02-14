"""
Fetch all Q5 (human) Wikidata IDs using QLever bulk query.
QLever can return millions of results efficiently.
"""

import json
import requests
from tqdm import tqdm

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"

QUERY = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?human WHERE {
  ?human wdt:P31 wd:Q5 .
}
"""

OUTPUT_FILE = "data/all_humans/all_human_ids.json"


def fetch_all_humans():
    print("Querying QLever for all Q5 (human) instances...")

    params = {
        "query": QUERY,
        "action": "tsv_export"  # TSV is faster for large results
    }

    response = requests.get(QLEVER_ENDPOINT, params=params, stream=True)
    response.raise_for_status()

    human_ids = []

    # Stream and parse TSV response
    lines = response.iter_lines(decode_unicode=True)
    header = next(lines)  # Skip header

    for line in tqdm(lines, desc="Parsing results", unit=" ids"):
        if line:
            # Extract Q-id from full URI
            # Format: <http://www.wikidata.org/entity/Q12345>
            uri = line.strip()
            if "/Q" in uri:
                qid = uri.split("/")[-1].rstrip(">")
                human_ids.append(qid)

    print(f"\nTotal humans found: {len(human_ids):,}")

    # Save to JSON
    with open(OUTPUT_FILE, "w") as f:
        json.dump(human_ids, f)

    print(f"Saved to {OUTPUT_FILE}")
    return human_ids


if __name__ == "__main__":
    fetch_all_humans()
