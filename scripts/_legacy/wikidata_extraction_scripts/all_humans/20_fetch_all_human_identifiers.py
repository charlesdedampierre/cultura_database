"""
Fetch ALL external identifiers for all humans using QLever bulk queries.

Strategy: Use a single massive query to get all identifiers at once,
similar to how we fetched birthdates/deathdates.

This is MUCH faster than batched individual queries because QLever
can return millions of rows efficiently.

Output: data/all_humans/all_human_identifiers.json
Format: {
  "Q123": {
    "P214": "12345",      # VIAF ID
    "P227": "67890",      # GND ID
    ...
  }
}
"""

import json
import requests
from tqdm import tqdm
import time

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"

# Query to get ALL external identifiers for ALL humans
# This returns: human_id, property_id, value
IDENTIFIERS_QUERY = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX wikibase: <http://wikiba.se/ontology#>

SELECT ?human ?prop ?value WHERE {
  ?human wdt:P31 wd:Q5 .
  ?human ?p ?value .
  ?prop wikibase:directClaim ?p .
  ?prop wikibase:propertyType wikibase:ExternalId .
}
"""

OUTPUT_FILE = "data/all_humans/all_human_identifiers.json"


def extract_id(uri: str) -> str:
    """Extract ID from full URI."""
    if "/" in uri:
        return uri.split("/")[-1].rstrip(">")
    return uri


def fetch_all_identifiers():
    print("=" * 60)
    print("FETCHING ALL EXTERNAL IDENTIFIERS")
    print("=" * 60)
    print(f"\nEndpoint: {QLEVER_ENDPOINT}")
    print("This may take several minutes for the query to complete...")
    print()

    start_time = time.time()

    params = {
        "query": IDENTIFIERS_QUERY,
        "action": "tsv_export"
    }

    print("Sending query to QLever...")
    response = requests.get(QLEVER_ENDPOINT, params=params, stream=True, timeout=3600)
    response.raise_for_status()

    query_time = time.time() - start_time
    print(f"Query accepted, streaming results... (query time: {query_time:.1f}s)")

    # Parse results
    identifiers = {}  # {qid: {prop_id: value, ...}}
    row_count = 0

    lines = response.iter_lines(decode_unicode=True)
    header = next(lines)  # Skip header

    for line in tqdm(lines, desc="Parsing identifiers", unit=" rows"):
        if line:
            parts = line.strip().split("\t")
            if len(parts) >= 3:
                human_id = extract_id(parts[0])
                prop_id = extract_id(parts[1])
                value = parts[2]

                # Clean value (remove quotes, language tags)
                if value.startswith('"'):
                    value = value.strip('"')
                    if "@" in value:
                        value = value.split("@")[0]

                if human_id not in identifiers:
                    identifiers[human_id] = {}

                # If same property appears multiple times, keep as list
                if prop_id in identifiers[human_id]:
                    existing = identifiers[human_id][prop_id]
                    if isinstance(existing, list):
                        if value not in existing:
                            existing.append(value)
                    else:
                        if existing != value:
                            identifiers[human_id][prop_id] = [existing, value]
                else:
                    identifiers[human_id][prop_id] = value

                row_count += 1

    elapsed = time.time() - start_time

    print(f"\nTotal rows parsed: {row_count:,}")
    print(f"Unique humans with identifiers: {len(identifiers):,}")

    # Save to JSON
    print(f"\nSaving to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w") as f:
        json.dump(identifiers, f)

    # Statistics
    total_ids = sum(len(v) for v in identifiers.values())
    avg_ids = total_ids / len(identifiers) if identifiers else 0

    print("\n" + "=" * 60)
    print("EXTRACTION COMPLETE")
    print("=" * 60)
    print(f"Humans with identifiers: {len(identifiers):,}")
    print(f"Total identifier values: {row_count:,}")
    print(f"Unique property types: {len(set(p for ids in identifiers.values() for p in ids)):,}")
    print(f"Avg identifiers per human: {avg_ids:.1f}")
    print(f"Time: {elapsed/60:.1f} minutes")
    print(f"Output: {OUTPUT_FILE}")

    return identifiers


if __name__ == "__main__":
    fetch_all_identifiers()
