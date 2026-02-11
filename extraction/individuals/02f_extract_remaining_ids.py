"""Extract remaining occupations using cursor-based pagination (IDs only, 10k per page)."""

import json
import os
import re
import time
import requests
from tqdm import tqdm

BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "extracted", "individuals", "occupation")

# Remaining occupations (excluding actor already done, writer and researcher too large)
OCCUPATIONS = [
    ("Q1622272", "university teacher", 316_059),
    ("Q201788", "historian", 120_733),
    ("Q188094", "economist", 56_666),
    ("Q1234713", "theologian", 43_556),
]

PAGE_SIZE = 10_000
DELAY = 2
ENDPOINT = "https://query.wikidata.org/sparql"
HEADERS = {"Accept": "application/json", "User-Agent": "CulturaDatabase/1.0"}


def clean_json(s):
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', s)


def sparql_query(query, timeout=180):
    for attempt in range(5):
        try:
            r = requests.get(ENDPOINT, params={"query": query}, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return json.loads(clean_json(r.text))["results"]["bindings"]
        except Exception as e:
            if attempt < 4:
                wait = 30 * (attempt + 1)
                print(f"    Error: {str(e)[:40]}, retry in {wait}s...")
                time.sleep(wait)
            else:
                return None


def extract_qnum(wikidata_id):
    return int(wikidata_id[1:])


def fetch_occupation(occ_id, occ_name, expected):
    print(f"\n{'='*60}")
    print(f"Extracting {occ_name} ({occ_id}) - expected ~{expected:,}")
    print(f"{'='*60}")

    all_ids = []
    last_qnum = 0
    page = 1

    pbar = tqdm(total=expected, desc=occ_name, unit=" ids")

    while True:
        query = f"""
        SELECT ?item WHERE {{
          ?item wdt:P106 wd:{occ_id} .
          BIND(xsd:integer(SUBSTR(STR(?item), 33)) AS ?num)
          FILTER(?num > {last_qnum})
        }}
        ORDER BY ?num
        LIMIT {PAGE_SIZE}
        """

        results = sparql_query(query)

        if results is None:
            tqdm.write(f"  Page {page}: FAILED after retries")
            break

        if not results:
            break

        for r in results:
            url = r["item"]["value"]
            wikidata_id = url.split("/")[-1]
            all_ids.append(wikidata_id)

        last_qnum = extract_qnum(all_ids[-1])
        pbar.update(len(results))

        if len(results) < PAGE_SIZE:
            break

        page += 1
        time.sleep(DELAY)

    pbar.close()

    # Save result
    filepath = os.path.join(OUTPUT_DIR, f"{occ_id}.json")
    data = {
        "occupation_id": occ_id,
        "occupation_name": occ_name,
        "count": len(all_ids),
        "results": [{"wikidata_id": wid} for wid in all_ids],
        "error": None,
    }
    with open(filepath, "w") as f:
        json.dump(data, f)

    print(f"Saved {len(all_ids):,} {occ_name}s")
    return len(all_ids)


def main():
    total_expected = sum(exp for _, _, exp in OCCUPATIONS)
    print(f"Extracting 4 occupations (~{total_expected:,} total)")

    results = []
    for occ_id, occ_name, expected in OCCUPATIONS:
        count = fetch_occupation(occ_id, occ_name, expected)
        results.append((occ_name, count))

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    total = 0
    for name, count in results:
        print(f"  {name:20} {count:>10,}")
        total += count
    print(f"  {'TOTAL':20} {total:>10,}")


if __name__ == "__main__":
    main()
