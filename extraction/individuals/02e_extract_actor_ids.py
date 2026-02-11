"""Extract actor IDs using cursor-based pagination (IDs only, 10k per page).

Uses numeric Q-number comparison for proper cursor pagination.
"""

import json
import os
import re
import time
import requests
from tqdm import tqdm

BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "extracted", "individuals", "occupation")

OCC_ID = "Q33999"
OCC_NAME = "actor"
PAGE_SIZE = 10_000
DELAY = 2
ENDPOINT = "https://query.wikidata.org/sparql"
HEADERS = {"Accept": "application/json", "User-Agent": "CulturaDatabase/1.0"}


def clean_json(s):
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', s)


def sparql_query(query, timeout=180):
    for attempt in range(3):
        try:
            r = requests.get(ENDPOINT, params={"query": query}, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return json.loads(clean_json(r.text))["results"]["bindings"]
        except Exception as e:
            if attempt < 2:
                wait = 30 * (attempt + 1)
                print(f"  Error: {str(e)[:40]}, retry in {wait}s...")
                time.sleep(wait)
            else:
                raise


def extract_qnum(wikidata_id):
    """Extract numeric part from Q-number (e.g., Q12345 -> 12345)."""
    return int(wikidata_id[1:])


def main():
    print(f"Extracting {OCC_NAME} ({OCC_ID}) - IDs only, {PAGE_SIZE:,}/page")
    print(f"Expected: ~365,000 actors = ~37 pages\n")

    all_ids = []
    last_qnum = 0  # Start from Q0 (effectively Q1)
    page = 1

    pbar = tqdm(total=365_000, desc="Fetching", unit=" ids")

    while True:
        # Use numeric comparison on Q-number
        # URL format: http://www.wikidata.org/entity/Q12345 (31 chars before Q, so pos 33 for number)
        query = f"""
        SELECT ?item WHERE {{
          ?item wdt:P106 wd:{OCC_ID} .
          BIND(xsd:integer(SUBSTR(STR(?item), 33)) AS ?num)
          FILTER(?num > {last_qnum})
        }}
        ORDER BY ?num
        LIMIT {PAGE_SIZE}
        """

        tqdm.write(f"Page {page}: Q > {last_qnum:,}...")

        results = sparql_query(query)

        if not results:
            tqdm.write(f"Page {page}: empty results, done!")
            break

        count_this_page = len(results)
        for r in results:
            url = r["item"]["value"]
            wikidata_id = url.split("/")[-1]
            all_ids.append(wikidata_id)

        # Get last Q-number for next cursor
        last_id = all_ids[-1]
        last_qnum = extract_qnum(last_id)

        pbar.update(count_this_page)
        tqdm.write(f"Page {page}: +{count_this_page:,} = {len(all_ids):,} (last: {last_id})")

        if count_this_page < PAGE_SIZE:
            tqdm.write(f"Page {page}: partial page, done!")
            break

        page += 1
        time.sleep(DELAY)

    pbar.close()

    # Save result
    filepath = os.path.join(OUTPUT_DIR, f"{OCC_ID}.json")
    data = {
        "occupation_id": OCC_ID,
        "occupation_name": OCC_NAME,
        "count": len(all_ids),
        "results": [{"wikidata_id": wid} for wid in all_ids],
        "error": None,
    }
    with open(filepath, "w") as f:
        json.dump(data, f)

    print(f"\nDone! {len(all_ids):,} actors saved")


if __name__ == "__main__":
    main()
