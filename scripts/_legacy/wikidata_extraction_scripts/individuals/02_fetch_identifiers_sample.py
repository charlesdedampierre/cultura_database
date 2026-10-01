"""
Fetch external identifiers for sample individuals from Wikidata.
QLever doesn't support wikibase ontology, so we use the regular Wikidata endpoint.
"""

import sqlite3
import sys
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from wikidata_api import sparql_query, set_endpoint

# Use regular Wikidata endpoint for identifiers (QLever doesn't support wikibase ontology)
WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"

SAMPLE_DB = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "sample", "individuals_qlever_sample.db"
)

NUM_THREADS = 5  # Lower threads to avoid rate limiting on Wikidata
BATCH_SIZE = 50


def get_identifiers(wiki_id: str) -> list:
    """Get external identifiers for an individual from Wikidata."""
    query = """
    SELECT ?prop ?propLabel ?value WHERE {
      ?prop wikibase:directClaim ?claim .
      ?prop wikibase:propertyType wikibase:ExternalId .
      wd:%s ?claim ?value .
      SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
    }
    """ % wiki_id

    try:
        rows = sparql_query(query)
        identifiers = []
        for row in rows:
            prop_url = row.get("prop", "")
            prop_id = prop_url.split("/")[-1] if "/" in prop_url else ""
            prop_name = row.get("propLabel", "")
            value = row.get("value", "")
            if prop_id and value:
                identifiers.append({
                    "property_id": prop_id,
                    "property_name": prop_name,
                    "value": value
                })
        return identifiers
    except Exception as e:
        print(f"  Error fetching identifiers for {wiki_id}: {e}")
        return []


def main():
    # Set Wikidata endpoint
    set_endpoint(WIKIDATA_ENDPOINT)
    print(f"Using endpoint: {WIKIDATA_ENDPOINT}")

    # Get all individual IDs from sample
    conn = sqlite3.connect(SAMPLE_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT wikidata_id, name FROM SAMPLE_individuals_information")
    individuals = cursor.fetchall()
    print(f"Total individuals in sample: {len(individuals):,}")

    all_identifiers = []
    properties = {}  # Track unique properties

    print(f"Fetching identifiers with {NUM_THREADS} threads...")
    print("(Using Wikidata endpoint - may be slower due to rate limiting)")

    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        future_to_id = {
            executor.submit(get_identifiers, ind[0]): (ind[0], ind[1])
            for ind in individuals
        }

        for future in tqdm(as_completed(future_to_id), total=len(individuals), desc="Fetching"):
            wiki_id, name = future_to_id[future]
            try:
                identifiers = future.result()
                for ident in identifiers:
                    all_identifiers.append({
                        "wikidata_id": wiki_id,
                        "name": name,
                        "property_id": ident["property_id"],
                        "property_name": ident["property_name"],
                        "value": ident["value"]
                    })
                    # Track properties
                    if ident["property_id"] not in properties:
                        properties[ident["property_id"]] = ident["property_name"]
            except Exception as e:
                print(f"  Error for {wiki_id}: {e}")

    print(f"\nTotal identifiers found: {len(all_identifiers):,}")
    print(f"Unique properties: {len(properties)}")

    # Insert into database
    print("\nInserting into SAMPLE_identifiers...")
    cursor.execute("DELETE FROM SAMPLE_identifiers")  # Clear existing
    cursor.execute("DELETE FROM SAMPLE_properties")  # Clear existing

    for ident in tqdm(all_identifiers, desc="Inserting identifiers"):
        cursor.execute("""
            INSERT INTO SAMPLE_identifiers (wikidata_id, name, property_id, property_name, value)
            VALUES (?, ?, ?, ?, ?)
        """, (ident["wikidata_id"], ident["name"], ident["property_id"],
              ident["property_name"], ident["value"]))

    # Insert properties
    print("Inserting properties...")
    for prop_id, prop_name in properties.items():
        cursor.execute("""
            INSERT INTO SAMPLE_properties (property_id, property_name, description, wikidata_url)
            VALUES (?, ?, ?, ?)
        """, (prop_id, prop_name, "", f"https://www.wikidata.org/wiki/Property:{prop_id}"))

    conn.commit()
    conn.close()

    print("\nDone!")
    print(f"Inserted {len(all_identifiers):,} identifiers")
    print(f"Inserted {len(properties)} properties")


if __name__ == "__main__":
    main()
