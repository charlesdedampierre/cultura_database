"""Extract country and coordinates for each deathcity from Wikidata.

For each unique deathcity, queries P17 (country) and P625 (coordinates).
Saves to data/extracted/individuals/deathcity_details.json.
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


def get_deathcity_details(city_id: str) -> dict | None:
    """Get country and coordinates for a deathcity."""
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
            "deathcity_wikidata_id": city_id,
            "country_wikidata_id": country_id,
            "country_name": country_name,
            "location": location,
        }
    except Exception as e:
        print(f"  Error for {city_id}: {e}")
        return None


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load individual info to get unique deathcities
    info_path = os.path.join(OUTPUT_DIR, "individual_info.json")
    with open(info_path) as f:
        individual_info = json.load(f)

    # Collect unique deathcity IDs
    deathcity_ids = set()
    for info in individual_info:
        if info.get("deathcities"):
            for dc in info["deathcities"]:
                dc_id = dc["deathcity_wikidata_id"]
                if dc_id.startswith("Q"):
                    deathcity_ids.add(dc_id)

    deathcity_ids = list(deathcity_ids)
    print(f"Extracting details for {len(deathcity_ids)} unique deathcities...")

    with Pool(NUM_WORKERS) as p:
        results = list(tqdm(
            p.imap(get_deathcity_details, deathcity_ids),
            total=len(deathcity_ids),
            desc="Deathcity details",
        ))

    results = [r for r in results if r is not None]

    output_path = os.path.join(OUTPUT_DIR, "deathcity_details.json")
    with open(output_path, "w") as f:
        json.dump(results, f)

    print(f"Saved details for {len(results)} deathcities to {output_path}")


if __name__ == "__main__":
    main()
