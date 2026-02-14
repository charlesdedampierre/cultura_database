"""
Fetch coordinates (latitude/longitude) for all birth and death places using QLever.
Uses P625 (coordinate location) and P17 (country) properties.
Uses POST requests to handle large batches.
"""

import json
import requests
import re
from tqdm import tqdm

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"

OUTPUT_DIR = "data/all_humans"


def extract_qid(uri: str) -> str:
    """Extract Q-id from full URI."""
    if "/Q" in uri:
        return uri.split("/")[-1].rstrip(">")
    return uri


def parse_coordinates(point_str: str) -> tuple:
    """Parse POINT(lon lat) format to (lat, lon) tuple."""
    match = re.search(r'POINT\(([+-]?\d+\.?\d*)\s+([+-]?\d+\.?\d*)\)', point_str, re.IGNORECASE)
    if match:
        lon = float(match.group(1))
        lat = float(match.group(2))
        return (lat, lon)
    return None


def get_unique_places():
    """Extract all unique place IDs from birthplaces and deathplaces."""
    print("Loading birthplaces and deathplaces...")

    places = {}

    with open(f"{OUTPUT_DIR}/all_human_birthplaces.json") as f:
        bp = json.load(f)

    for human_id, place_data in bp.items():
        if isinstance(place_data, dict) and 'id' in place_data:
            place_id = place_data['id']
            place_name = place_data.get('name', '')
            if place_name.endswith('@en'):
                place_name = place_name[:-3]
            place_name = place_name.strip('"')
            if place_id not in places:
                places[place_id] = place_name

    print(f"Unique birthplaces: {len(places):,}")

    with open(f"{OUTPUT_DIR}/all_human_deathplaces.json") as f:
        dp = json.load(f)

    initial_count = len(places)
    for human_id, place_data in dp.items():
        if isinstance(place_data, dict) and 'id' in place_data:
            place_id = place_data['id']
            place_name = place_data.get('name', '')
            if place_name.endswith('@en'):
                place_name = place_name[:-3]
            place_name = place_name.strip('"')
            if place_id not in places:
                places[place_id] = place_name

    print(f"Additional deathplaces: {len(places) - initial_count:,}")
    print(f"Total unique places: {len(places):,}")

    return places


def fetch_coordinates_batch(place_ids: list) -> dict:
    """Fetch coordinates for a batch of place IDs using POST."""
    values = " ".join([f"wd:{qid}" for qid in place_ids])

    query = f"""
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?place ?coords WHERE {{
  VALUES ?place {{ {values} }}
  ?place wdt:P625 ?coords .
}}
"""

    data = {
        "query": query,
        "action": "tsv_export"
    }

    response = requests.post(QLEVER_ENDPOINT, data=data)
    response.raise_for_status()

    results = {}
    lines = response.text.strip().split("\n")

    for line in lines[1:]:  # Skip header
        if line:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                qid = extract_qid(parts[0])
                coords = parse_coordinates(parts[1])
                if coords:
                    results[qid] = coords

    return results


def fetch_countries_batch(place_ids: list) -> dict:
    """Fetch country for a batch of place IDs using POST."""
    values = " ".join([f"wd:{qid}" for qid in place_ids])

    query = f"""
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?place ?country ?countryLabel WHERE {{
  VALUES ?place {{ {values} }}
  ?place wdt:P17 ?country .
  ?country rdfs:label ?countryLabel .
  FILTER(LANG(?countryLabel) = "en")
}}
"""

    data = {
        "query": query,
        "action": "tsv_export"
    }

    response = requests.post(QLEVER_ENDPOINT, data=data)
    response.raise_for_status()

    results = {}
    lines = response.text.strip().split("\n")

    for line in lines[1:]:  # Skip header
        if line:
            parts = line.strip().split("\t")
            if len(parts) >= 3:
                place_qid = extract_qid(parts[0])
                country_qid = extract_qid(parts[1])
                # Remove language tag properly (e.g., "France"@en -> France)
                country_name = parts[2]
                if country_name.endswith('@en'):
                    country_name = country_name[:-3]
                country_name = country_name.strip('"')
                if place_qid not in results:
                    results[place_qid] = {
                        "country_id": country_qid,
                        "country_name": country_name
                    }

    return results


def main():
    # Get all unique places from our data
    our_places = get_unique_places()
    place_ids = list(our_places.keys())

    # Fetch coordinates in batches using POST
    print("\nFetching coordinates from QLever...")
    batch_size = 2000  # Larger batches with POST
    all_coords = {}

    for i in tqdm(range(0, len(place_ids), batch_size), desc="Fetching coordinates"):
        batch = place_ids[i:i+batch_size]
        try:
            coords = fetch_coordinates_batch(batch)
            all_coords.update(coords)
        except Exception as e:
            print(f"\nError in batch {i}: {e}")
            continue

    print(f"Places with coordinates: {len(all_coords):,}")

    # Fetch countries in batches using POST
    print("\nFetching countries from QLever...")
    all_countries = {}

    for i in tqdm(range(0, len(place_ids), batch_size), desc="Fetching countries"):
        batch = place_ids[i:i+batch_size]
        try:
            countries = fetch_countries_batch(batch)
            all_countries.update(countries)
        except Exception as e:
            print(f"\nError in batch {i}: {e}")
            continue

    print(f"Places with country info: {len(all_countries):,}")

    # Combine all place information
    print("\nBuilding final place info...")
    place_info = {}

    for place_id, place_name in tqdm(our_places.items(), desc="Building place info"):
        info = {"name": place_name}

        if place_id in all_coords:
            info["lat"] = all_coords[place_id][0]
            info["lon"] = all_coords[place_id][1]

        if place_id in all_countries:
            info["country_id"] = all_countries[place_id]["country_id"]
            info["country_name"] = all_countries[place_id]["country_name"]

        place_info[place_id] = info

    # Save results
    output_file = f"{OUTPUT_DIR}/place_locations.json"
    with open(output_file, "w") as f:
        json.dump(place_info, f, indent=2, ensure_ascii=False)

    # Summary
    with_coords = sum(1 for p in place_info.values() if "lat" in p)
    with_country = sum(1 for p in place_info.values() if "country_id" in p)

    print(f"\n=== Summary ===")
    print(f"Total unique places in our data: {len(place_info):,}")
    print(f"Places with coordinates: {with_coords:,} ({100*with_coords/len(place_info):.1f}%)")
    print(f"Places with country: {with_country:,} ({100*with_country/len(place_info):.1f}%)")
    print(f"Saved to {output_file}")


if __name__ == "__main__":
    main()
