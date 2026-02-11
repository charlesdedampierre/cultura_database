"""Extract country and coordinates for each birthcity from Wikidata.

For each unique birthcity, queries P17 (country) and P625 (coordinates).
Saves to data/extracted/individuals/birthcity_details.json.
"""

import json
import os
import sys
from multiprocessing import Pool

from tqdm import tqdm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from wikidata_api import sparql_query

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "extracted", "individuals")
NUM_WORKERS = 8


def get_birthcity_details(city_id: str) -> dict | None:
    """Get country and coordinates for a birthcity."""
    query = """
    SELECT ?country ?countryLabel ?location
    WHERE {
      OPTIONAL { wd:%s wdt:P17 ?country. }
      OPTIONAL { wd:%s wdt:P625 ?location. }
      SERVICE wikibase:label { bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }
    }
    """ % (city_id, city_id)

    try:
        rows = sparql_query(query)
        if not rows:
            return None

        row = rows[0]
        country_url = row.get("country", "")
        country_id = country_url.split("/")[-1] if country_url else None
        country_name = row.get("countryLabel", "")
        location = row.get("location", "")

        return {
            "birthcity_wikidata_id": city_id,
            "country_wikidata_id": country_id,
            "country_name": country_name,
            "location": location,
        }
    except Exception as e:
        print(f"  Error for {city_id}: {e}")
        return None


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load individual info to get unique birthcities
    info_path = os.path.join(OUTPUT_DIR, "individual_info.json")
    with open(info_path) as f:
        individual_info = json.load(f)

    # Collect unique birthcity IDs
    birthcity_ids = set()
    for info in individual_info:
        if info.get("birthcities"):
            for bc in info["birthcities"]:
                bc_id = bc["birthcity_wikidata_id"]
                # Skip blank node IDs
                if bc_id.startswith("Q"):
                    birthcity_ids.add(bc_id)

    birthcity_ids = list(birthcity_ids)
    print(f"Extracting details for {len(birthcity_ids)} unique birthcities...")

    with Pool(NUM_WORKERS) as p:
        results = list(tqdm(
            p.imap(get_birthcity_details, birthcity_ids),
            total=len(birthcity_ids),
            desc="Birthcity details",
        ))

    results = [r for r in results if r is not None]

    output_path = os.path.join(OUTPUT_DIR, "birthcity_details.json")
    with open(output_path, "w") as f:
        json.dump(results, f)

    print(f"Saved details for {len(results)} birthcities to {output_path}")


if __name__ == "__main__":
    main()
