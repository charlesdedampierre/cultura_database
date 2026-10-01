"""
Fetch modern country mapping for all nationalities using QLever.
Maps historical entities (dynasties, empires) to their modern country equivalents.
"""

import json
import requests
from tqdm import tqdm

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"
OUTPUT_DIR = "data/all_humans"


def extract_qid(uri: str) -> str:
    """Extract Q-id from full URI."""
    if "/Q" in uri:
        return uri.split("/")[-1].rstrip(">")
    return uri


def get_unique_nationalities():
    """Extract all unique nationality IDs from the data."""
    print("Loading nationalities...")

    with open(f"{OUTPUT_DIR}/all_human_nationalities.json") as f:
        nat = json.load(f)

    nationalities = {}
    for human_id, nat_list in nat.items():
        if isinstance(nat_list, list):
            for nat_data in nat_list:
                if isinstance(nat_data, dict) and 'id' in nat_data:
                    nat_id = nat_data['id']
                    nat_name = nat_data.get('name', '')
                    if nat_name.endswith('@en'):
                        nat_name = nat_name[:-3]
                    nat_name = nat_name.strip('"')
                    if nat_id not in nationalities:
                        nationalities[nat_id] = nat_name

    print(f"Unique nationalities: {len(nationalities)}")
    return nationalities


def fetch_country_batch(nat_ids: list) -> dict:
    """Fetch country (P17) for a batch of nationality IDs using POST."""
    values = " ".join([f"wd:{qid}" for qid in nat_ids])

    # Query for P17 (country) - works for regions, cities, historical entities
    query = f"""
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?nat ?country ?countryLabel WHERE {{
  VALUES ?nat {{ {values} }}
  ?nat wdt:P17 ?country .
  ?country rdfs:label ?countryLabel .
  FILTER(LANG(?countryLabel) = "en")
}}
"""

    data = {"query": query, "action": "tsv_export"}
    response = requests.post(QLEVER_ENDPOINT, data=data)
    response.raise_for_status()

    results = {}
    lines = response.text.strip().split("\n")

    for line in lines[1:]:
        if line:
            parts = line.strip().split("\t")
            if len(parts) >= 3:
                nat_qid = extract_qid(parts[0])
                country_qid = extract_qid(parts[1])
                country_name = parts[2]
                if country_name.endswith('@en'):
                    country_name = country_name[:-3]
                country_name = country_name.strip('"')
                if nat_qid not in results:
                    results[nat_qid] = {
                        "country_id": country_qid,
                        "country_name": country_name
                    }

    return results


def fetch_instance_of_country_batch(nat_ids: list) -> dict:
    """Check if nationality IS a country (P31 = Q6256 or subclass)."""
    values = " ".join([f"wd:{qid}" for qid in nat_ids])

    query = f"""
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?nat ?natLabel WHERE {{
  VALUES ?nat {{ {values} }}
  ?nat wdt:P31/wdt:P279* wd:Q6256 .
  ?nat rdfs:label ?natLabel .
  FILTER(LANG(?natLabel) = "en")
}}
"""

    data = {"query": query, "action": "tsv_export"}
    response = requests.post(QLEVER_ENDPOINT, data=data)
    response.raise_for_status()

    results = {}
    lines = response.text.strip().split("\n")

    for line in lines[1:]:
        if line:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                nat_qid = extract_qid(parts[0])
                nat_name = parts[1]
                if nat_name.endswith('@en'):
                    nat_name = nat_name[:-3]
                nat_name = nat_name.strip('"')
                # This nationality IS a country, so it maps to itself
                results[nat_qid] = {
                    "country_id": nat_qid,
                    "country_name": nat_name
                }

    return results


def fetch_replaced_by_batch(nat_ids: list) -> dict:
    """Fetch P1366 (replaced by) for historical entities."""
    values = " ".join([f"wd:{qid}" for qid in nat_ids])

    query = f"""
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?nat ?successor ?successorLabel WHERE {{
  VALUES ?nat {{ {values} }}
  ?nat wdt:P1366+ ?successor .
  ?successor wdt:P31/wdt:P279* wd:Q6256 .
  ?successor rdfs:label ?successorLabel .
  FILTER(LANG(?successorLabel) = "en")
}}
"""

    data = {"query": query, "action": "tsv_export"}
    response = requests.post(QLEVER_ENDPOINT, data=data)
    response.raise_for_status()

    results = {}
    lines = response.text.strip().split("\n")

    for line in lines[1:]:
        if line:
            parts = line.strip().split("\t")
            if len(parts) >= 3:
                nat_qid = extract_qid(parts[0])
                successor_qid = extract_qid(parts[1])
                successor_name = parts[2]
                if successor_name.endswith('@en'):
                    successor_name = successor_name[:-3]
                successor_name = successor_name.strip('"')
                if nat_qid not in results:
                    results[nat_qid] = {
                        "country_id": successor_qid,
                        "country_name": successor_name
                    }

    return results


def main():
    # Get all unique nationalities
    nationalities = get_unique_nationalities()
    nat_ids = list(nationalities.keys())

    batch_size = 500
    all_countries = {}

    # Step 1: Check if nationality IS a country
    print("\nChecking which nationalities are countries...")
    for i in tqdm(range(0, len(nat_ids), batch_size), desc="Instance of country"):
        batch = nat_ids[i:i+batch_size]
        try:
            results = fetch_instance_of_country_batch(batch)
            all_countries.update(results)
        except Exception as e:
            print(f"\nError in batch {i}: {e}")
            continue

    print(f"Nationalities that ARE countries: {len(all_countries)}")

    # Step 2: For remaining, fetch P17 (country)
    remaining = [qid for qid in nat_ids if qid not in all_countries]
    print(f"\nFetching P17 (country) for {len(remaining)} remaining nationalities...")

    for i in tqdm(range(0, len(remaining), batch_size), desc="Fetching P17"):
        batch = remaining[i:i+batch_size]
        try:
            results = fetch_country_batch(batch)
            all_countries.update(results)
        except Exception as e:
            print(f"\nError in batch {i}: {e}")
            continue

    print(f"Total with country mapping: {len(all_countries)}")

    # Step 3: For still remaining, try P1366 (replaced by)
    remaining = [qid for qid in nat_ids if qid not in all_countries]
    print(f"\nFetching P1366 (replaced by) for {len(remaining)} remaining...")

    for i in tqdm(range(0, len(remaining), batch_size), desc="Fetching P1366"):
        batch = remaining[i:i+batch_size]
        try:
            results = fetch_replaced_by_batch(batch)
            all_countries.update(results)
        except Exception as e:
            print(f"\nError in batch {i}: {e}")
            continue

    print(f"Total with country mapping: {len(all_countries)}")

    # Build final mapping
    print("\nBuilding final nationality to country mapping...")
    nationality_countries = {}

    for nat_id, nat_name in tqdm(nationalities.items(), desc="Building mapping"):
        info = {"name": nat_name}
        if nat_id in all_countries:
            info["country_id"] = all_countries[nat_id]["country_id"]
            info["country_name"] = all_countries[nat_id]["country_name"]
        nationality_countries[nat_id] = info

    # Save results
    output_file = f"{OUTPUT_DIR}/nationality_countries.json"
    with open(output_file, "w") as f:
        json.dump(nationality_countries, f, indent=2, ensure_ascii=False)

    # Summary
    with_country = sum(1 for n in nationality_countries.values() if "country_id" in n)

    print(f"\n=== Summary ===")
    print(f"Total unique nationalities: {len(nationality_countries)}")
    print(f"With country mapping: {with_country} ({100*with_country/len(nationality_countries):.1f}%)")
    print(f"Saved to {output_file}")


if __name__ == "__main__":
    main()
