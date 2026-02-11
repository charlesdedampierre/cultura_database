"""Extract all sub-occupations of writer, artist, and scientist from Wikidata.

Uses P279* (subclass of) on seed occupation Q-IDs to get the full
occupation hierarchy. Saves results to data/extracted/individuals/occupations.json.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from wikidata_api import sparql_query

OUTPUT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "extracted", "individuals"
)

# Seed occupations: artist (Q483501), scientist (Q901), writer (Q36180)
SEED_OCCUPATIONS = {
    "Q483501": "artist",
    "Q901": "scientist",
    "Q36180": "writer",
}


def extract_sub_occupations(seed_id: str, category: str) -> list[dict]:
    """Get all sub-occupations (P279*) for a seed occupation."""
    query = (
        """
    SELECT ?item ?itemLabel
    WHERE {
      ?item wdt:P279* wd:%s .
      SERVICE wikibase:label { bd:serviceParam wikibase:language 'en'. }
    }
    """
        % seed_id
    )

    print(f"Querying sub-occupations for {category} ({seed_id})...")
    rows = sparql_query(query)

    results = []
    for row in rows:
        wikidata_id = row["item"].split("/")[-1]
        results.append(
            {
                "occupation_wikidata_id": wikidata_id,
                "occupation_name": row.get("itemLabel", ""),
                "occupation_category": category,
            }
        )

    print(f"  Found {len(results)} sub-occupations for {category}")
    return results


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    all_occupations = []
    for seed_id, category in SEED_OCCUPATIONS.items():
        occupations = extract_sub_occupations(seed_id, category)
        all_occupations.extend(occupations)

    # Deduplicate by wikidata_id (keep first category encountered)
    seen = {}
    deduped = []
    for occ in all_occupations:
        oid = occ["occupation_wikidata_id"]
        if oid not in seen:
            seen[oid] = True
            deduped.append(occ)

    output_path = os.path.join(OUTPUT_DIR, "occupations.json")
    with open(output_path, "w") as f:
        json.dump(deduped, f, indent=2)

    print(f"Saved {len(deduped)} occupations to {output_path}")


if __name__ == "__main__":
    main()
