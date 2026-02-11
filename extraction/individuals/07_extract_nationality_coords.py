"""Extract coordinates for nationality entities from Wikidata.

For each unique nationality Q-ID, queries P625 (coordinates).
Saves to data/extracted/individuals/nationality_coords.json.
"""

import json
import os
import sys
from multiprocessing import Pool

from tqdm import tqdm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from wikidata_api import sparql_query

OUTPUT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "extracted", "individuals"
)
NUM_WORKERS = 8


def get_nationality_coords(nationality_id: str) -> dict | None:
    """Get coordinates for a nationality entity."""
    query = (
        """
    SELECT ?item
    WHERE {
      wd:%s wdt:P625 ?item .
      SERVICE wikibase:label { bd:serviceParam wikibase:language 'en'. }
    }
    """
        % nationality_id
    )

    try:
        rows = sparql_query(query)
        if not rows:
            return None

        location = rows[0].get("item", "")

        return {
            "nationality_wikidata_id": nationality_id,
            "location": location,
        }
    except Exception as e:
        print(f"  Error for {nationality_id}: {e}")
        return None


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load individual info to get unique nationality IDs
    info_path = os.path.join(OUTPUT_DIR, "individual_info.json")
    with open(info_path) as f:
        individual_info = json.load(f)

    nationality_ids = set()
    for info in individual_info:
        if info.get("nationalities"):
            for nat in info["nationalities"]:
                nat_id = nat["nationality_wikidata_id"]
                if nat_id.startswith("Q"):
                    nationality_ids.add(nat_id)

    nationality_ids = list(nationality_ids)
    print(f"Extracting coordinates for {len(nationality_ids)} unique nationalities...")

    with Pool(NUM_WORKERS) as p:
        results = list(
            tqdm(
                p.imap(get_nationality_coords, nationality_ids),
                total=len(nationality_ids),
                desc="Nationality coords",
            )
        )

    results = [r for r in results if r is not None]

    output_path = os.path.join(OUTPUT_DIR, "nationality_coords.json")
    with open(output_path, "w") as f:
        json.dump(results, f)

    print(f"Saved coordinates for {len(results)} nationalities to {output_path}")


if __name__ == "__main__":
    main()
