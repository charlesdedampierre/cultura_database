"""Extract writer IDs using cursor-based pagination (IDs only, 50k per page)."""

import json
import os
import re
import time
import requests
from tqdm import tqdm

BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "extracted", "individuals", "occupation")

OCC_ID = "Q36180"
OCC_NAME = "writer"
EXPECTED = 680_000
PAGE_SIZE = 50_000
DELAY = 3
ENDPOINT = "https://query.wikidata.org/sparql"
HEADERS = {"Accept": "application/json", "User-Agent": "CulturaDatabase/1.0"}


def clean_json(s):
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', s)


def sparql_query(query, timeout=300):
    for attempt in range(5):
        try:
            r = requests.get(ENDPOINT, params={"query": query}, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return json.loads(clean_json(r.text))["results"]["bindings"]
        except Exception as e:
            if attempt < 4:
                wait = 60 * (attempt + 1)
                print(f"    Error: {str(e)[:50]}, retry in {wait}s...")
                time.sleep(wait)
            else:
                return None


def extract_qnum(wikidata_id):
    return int(wikidata_id[1:])


def main():
    print(f"Extracting {OCC_NAME} ({OCC_ID}) - IDs only, {PAGE_SIZE:,}/page")
    print(f"Expected: ~{EXPECTED:,} = ~{EXPECTED // PAGE_SIZE} pages\n")

    all_ids = []
    last_qnum = 0
    page = 1

    pbar = tqdm(total=EXPECTED, desc="Fetching", unit=" ids")

    while True:
        query = f"""
        SELECT ?item WHERE {{
          ?item wdt:P106 wd:{OCC_ID} .
          BIND(xsd:integer(SUBSTR(STR(?item), 33)) AS ?num)
          FILTER(?num > {last_qnum})
        }}
        ORDER BY ?num
        LIMIT {PAGE_SIZE}
        """

        results = sparql_query(query)

        if results is None:
            tqdm.write(f"Page {page}: FAILED after retries, saving progress...")
            break

        if not results:
            tqdm.write(f"Page {page}: empty, done!")
            break

        for r in results:
            url = r["item"]["value"]
            wikidata_id = url.split("/")[-1]
            all_ids.append(wikidata_id)

        last_qnum = extract_qnum(all_ids[-1])
        pbar.update(len(results))

        tqdm.write(f"Page {page}: +{len(results):,} = {len(all_ids):,} (last: Q{last_qnum})")

        if len(results) < PAGE_SIZE:
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

    print(f"\nDone! {len(all_ids):,} writers saved")


if __name__ == "__main__":
    main()
