"""
Enrich identifier_types table with metadata from Wikidata:
- description: Property description
- issuer_name, issuer_id, issuer_instance: Who issues this identifier
- country_name, country_id: Country associated with the identifier
- inception: When the identifier was created
- database_records: Number of records in the database
- website: Official website

Run: python 04_enrich_identifier_metadata.py ../../data/humans_clean.sqlite3
"""

import sqlite3
import requests
import sys
from tqdm import tqdm
import time

QLEVER_URL = "https://qlever.cs.uni-freiburg.de/api/wikidata"
BATCH_SIZE = 100  # Larger batches for QLever (faster, no rate limits)


def fetch_identifier_metadata(property_ids: list[str]) -> dict:
    """Fetch metadata for a batch of property IDs from QLever."""
    if not property_ids:
        return {}

    values = " ".join([f"wd:{pid}" for pid in property_ids])

    # QLever query - no SERVICE clause needed, uses rdfs:label directly
    query = f"""
    PREFIX wd: <http://www.wikidata.org/entity/>
    PREFIX wdt: <http://www.wikidata.org/prop/direct/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX schema: <http://schema.org/>

    SELECT ?prop ?propLabel ?propDescription
           ?issuer ?issuerLabel ?issuerInstanceLabel
           ?country ?countryLabel
           ?inception
           ?databaseRecords
           ?website
    WHERE {{
        VALUES ?prop {{ {values} }}

        OPTIONAL {{ ?prop rdfs:label ?propLabel . FILTER(LANG(?propLabel) = "en") }}
        OPTIONAL {{ ?prop schema:description ?propDescription . FILTER(LANG(?propDescription) = "en") }}
        OPTIONAL {{
            {{ ?prop wdt:P126 ?issuer }} UNION {{ ?prop wdt:P137 ?issuer }}
            OPTIONAL {{ ?issuer rdfs:label ?issuerLabel . FILTER(LANG(?issuerLabel) = "en") }}
            OPTIONAL {{ ?issuer wdt:P31 ?issuerInstance . ?issuerInstance rdfs:label ?issuerInstanceLabel . FILTER(LANG(?issuerInstanceLabel) = "en") }}
        }}
        OPTIONAL {{
            ?prop wdt:P17 ?country .
            OPTIONAL {{ ?country rdfs:label ?countryLabel . FILTER(LANG(?countryLabel) = "en") }}
        }}
        OPTIONAL {{ ?prop wdt:P571 ?inception . }}
        OPTIONAL {{ ?prop wdt:P4876 ?databaseRecords . }}
        OPTIONAL {{ ?prop wdt:P856 ?website . }}
    }}
    """

    try:
        response = requests.get(
            QLEVER_URL,
            params={"query": query},
            headers={"Accept": "application/json", "User-Agent": "CulturaDatabase/1.0"},
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()

        results = {}
        for binding in data.get("results", {}).get("bindings", []):
            prop_uri = binding.get("prop", {}).get("value", "")
            prop_id = prop_uri.split("/")[-1] if prop_uri else None
            if not prop_id:
                continue

            if prop_id not in results:
                results[prop_id] = {
                    "description": None,
                    "issuer_name": None,
                    "issuer_id": None,
                    "issuer_instance": None,
                    "country_name": None,
                    "country_id": None,
                    "inception": None,
                    "database_records": None,
                    "website": None,
                }

            # Update with values (first non-null wins)
            if not results[prop_id]["description"]:
                results[prop_id]["description"] = binding.get("propDescription", {}).get("value")

            if not results[prop_id]["issuer_name"]:
                results[prop_id]["issuer_name"] = binding.get("issuerLabel", {}).get("value")
                issuer_uri = binding.get("issuer", {}).get("value", "")
                results[prop_id]["issuer_id"] = issuer_uri.split("/")[-1] if issuer_uri and "/Q" in issuer_uri else None

            if not results[prop_id]["issuer_instance"]:
                results[prop_id]["issuer_instance"] = binding.get("issuerInstanceLabel", {}).get("value")

            if not results[prop_id]["country_name"]:
                results[prop_id]["country_name"] = binding.get("countryLabel", {}).get("value")
                country_uri = binding.get("country", {}).get("value", "")
                results[prop_id]["country_id"] = country_uri.split("/")[-1] if country_uri and "/Q" in country_uri else None

            if not results[prop_id]["inception"]:
                inception = binding.get("inception", {}).get("value")
                if inception:
                    results[prop_id]["inception"] = inception[:10]  # Just date part

            if not results[prop_id]["database_records"]:
                results[prop_id]["database_records"] = binding.get("databaseRecords", {}).get("value")

            if not results[prop_id]["website"]:
                results[prop_id]["website"] = binding.get("website", {}).get("value")

        return results

    except Exception as e:
        print(f"  Warning: Batch failed: {e}")
        return {}


def main():
    if len(sys.argv) < 2:
        print("Usage: python 04_enrich_identifier_metadata.py <database_path>")
        sys.exit(1)

    db_path = sys.argv[1]

    print("=" * 60)
    print("ENRICH IDENTIFIER METADATA")
    print("=" * 60)

    # Connect to database
    print("\n[1/4] Opening database...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    print(f"  Opened {db_path}")

    # Add columns if they don't exist
    print("\n[2/4] Adding columns to identifier_types...")
    new_columns = [
        ("description", "TEXT"),
        ("issuer_name", "TEXT"),
        ("issuer_id", "TEXT"),
        ("issuer_instance", "TEXT"),
        ("country_name", "TEXT"),
        ("country_id", "TEXT"),
        ("inception", "TEXT"),
        ("database_records", "TEXT"),
        ("website", "TEXT"),
    ]

    for col_name, col_type in new_columns:
        try:
            cursor.execute(f"ALTER TABLE identifier_types ADD COLUMN {col_name} {col_type}")
            print(f"  Added column: {col_name}")
        except sqlite3.OperationalError:
            print(f"  Column exists: {col_name}")

    conn.commit()

    # Get all property IDs
    print("\n[3/4] Getting property IDs to enrich...")
    cursor.execute("SELECT property_id FROM identifier_types WHERE description IS NULL ORDER BY count DESC")
    property_ids = [row[0] for row in cursor.fetchall()]
    print(f"  Found {len(property_ids)} properties to enrich")

    if not property_ids:
        print("  Nothing to enrich!")
        conn.close()
        return

    # Fetch metadata from QLever
    print("\n[4/4] Fetching metadata from QLever...")
    n_batches = (len(property_ids) + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"  {n_batches} batches of {BATCH_SIZE} properties each")

    total_updated = 0
    batches = [property_ids[i : i + BATCH_SIZE] for i in range(0, len(property_ids), BATCH_SIZE)]

    pbar = tqdm(batches, desc="  Fetching", unit="batch")
    for batch in pbar:
        metadata = fetch_identifier_metadata(batch)
        batch_updated = 0

        for prop_id, data in metadata.items():
            cursor.execute(
                """
                UPDATE identifier_types
                SET description = ?,
                    issuer_name = ?,
                    issuer_id = ?,
                    issuer_instance = ?,
                    country_name = ?,
                    country_id = ?,
                    inception = ?,
                    database_records = ?,
                    website = ?
                WHERE property_id = ?
                """,
                (
                    data["description"],
                    data["issuer_name"],
                    data["issuer_id"],
                    data["issuer_instance"],
                    data["country_name"],
                    data["country_id"],
                    data["inception"],
                    data["database_records"],
                    data["website"],
                    prop_id,
                ),
            )
            if cursor.rowcount > 0:
                batch_updated += 1
                total_updated += 1

        conn.commit()
        pbar.set_postfix({"updated": total_updated, "batch": batch_updated})
        time.sleep(0.1)  # Small delay for QLever

    print(f"\n  Updated {total_updated} properties with metadata")

    # Show sample
    print("\n  Sample enriched data:")
    print("  " + "-" * 100)
    cursor.execute(
        """
        SELECT property_id, name_en, count, description, issuer_name, country_name, website
        FROM identifier_types
        WHERE description IS NOT NULL
        ORDER BY count DESC
        LIMIT 10
        """
    )
    for row in cursor.fetchall():
        prop_id, name, count, desc, issuer, country, website = row
        desc_short = (desc[:40] + "...") if desc and len(desc) > 40 else desc
        print(f"  {prop_id:8} | {name[:25]:25} | {count:8} | {desc_short or '-'}")
    print("  " + "-" * 100)

    conn.close()
    print("\n" + "=" * 60)
    print("DONE!")
    print("=" * 60)


if __name__ == "__main__":
    main()
