"""
Fetch identifier property names from QLever (Wikidata SPARQL endpoint)
and update the identifier_types table.

Run: python 01_fetch_identifier_names.py ../data/humans_clean.sqlite3
"""

import sqlite3
import requests
import sys
from tqdm import tqdm
import time

SPARQL_URL = "https://query.wikidata.org/sparql"
BATCH_SIZE = 50  # Smaller batches for Wikidata endpoint


def fetch_batch(property_ids: list[str]) -> dict[str, str]:
    """Fetch labels for a batch of property IDs from Wikidata SPARQL."""
    if not property_ids:
        return {}

    # Build SPARQL query with VALUES clause
    values = " ".join(f"wd:{p}" for p in property_ids)
    query = f"""
    SELECT ?prop ?propLabel WHERE {{
        VALUES ?prop {{ {values} }}
        ?prop rdfs:label ?propLabel .
        FILTER(LANG(?propLabel) = 'en')
    }}
    """

    try:
        response = requests.get(
            SPARQL_URL,
            params={"query": query, "format": "json"},
            headers={"User-Agent": "CulturaDatabase/1.0 (contact@example.com)"},
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()

        labels = {}
        for binding in data.get("results", {}).get("bindings", []):
            prop_uri = binding.get("prop", {}).get("value", "")
            label = binding.get("propLabel", {}).get("value", "")
            # Extract P number from URI
            prop_id = prop_uri.rsplit("/", 1)[-1]
            if prop_id.startswith("P"):
                labels[prop_id] = label

        return labels

    except Exception as e:
        print(f"\n  Warning: Batch failed: {e}")
        return {}


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <database.sqlite3>")
        sys.exit(1)

    db_path = sys.argv[1]

    print("=" * 60)
    print("FETCH IDENTIFIER NAMES FROM QLEVER")
    print("=" * 60)
    print()

    # Open database
    print("[1/3] Opening database...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    print(f"  Opened {db_path}")

    # Get all property IDs that need labels
    print("\n[2/3] Fetching property IDs...")
    cursor.execute(
        "SELECT property_id FROM identifier_types WHERE name_en IS NULL ORDER BY property_id"
    )
    property_ids = [row[0] for row in cursor.fetchall()]
    print(f"  Found {len(property_ids)} properties without labels")

    if not property_ids:
        print("\n  All properties already have labels. Nothing to do.")
        conn.close()
        return

    # Fetch labels from Wikidata SPARQL
    print("\n[3/3] Fetching labels from Wikidata SPARQL...")

    total_updated = 0
    batches = [
        property_ids[i : i + BATCH_SIZE]
        for i in range(0, len(property_ids), BATCH_SIZE)
    ]

    for batch in tqdm(batches, desc="  Fetching"):
        labels = fetch_batch(batch)

        for prop_id, label in labels.items():
            cursor.execute(
                "UPDATE identifier_types SET name_en = ? WHERE property_id = ?",
                (label, prop_id),
            )
            total_updated += 1

        conn.commit()
        time.sleep(0.5)  # Be nice to Wikidata rate limits

    print(f"\n  Updated {total_updated} property labels")

    # Show sample
    print("\n  Sample results:")
    cursor.execute(
        "SELECT property_id, name_en FROM identifier_types WHERE name_en IS NOT NULL LIMIT 10"
    )
    for prop_id, name in cursor.fetchall():
        print(f"    {prop_id} -> {name}")

    conn.close()

    print("\n" + "=" * 60)
    print("DONE!")
    print("=" * 60)


if __name__ == "__main__":
    main()
