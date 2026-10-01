"""
Create a properties_definition table with all properties used in the database.
Fetches property metadata from QLever.

Properties used in individuals table:
- gender, birthdate, deathdate, birthcity_id, deathcity_id
- nationalities (P27), occupations (P106), etc.

Run: python 09_create_properties_table.py ../../data/humans_clean.sqlite3
"""

import sqlite3
import requests
import sys
from tqdm import tqdm
import time

QLEVER_URL = "https://qlever.cs.uni-freiburg.de/api/wikidata"

# Properties used in the database (mapped to their Wikidata property IDs)
PROPERTIES = {
    # Core individual properties
    "P21": "gender",
    "P569": "date of birth",
    "P570": "date of death",
    "P19": "place of birth",
    "P20": "place of death",
    "P27": "country of citizenship",
    "P106": "occupation",
    "P101": "field of work",
    "P39": "position held",
    "P1412": "languages spoken, written or signed",
    "P103": "native language",
    "P6886": "writing language",
    # Additional properties
    "P31": "instance of",
    "P279": "subclass of",
    "P17": "country",
    "P30": "continent",
    "P298": "ISO 3166-1 alpha-3 code",
    "P297": "ISO 3166-1 alpha-2 code",
    "P625": "coordinate location",
    "P856": "official website",
    "P18": "image",
    "P910": "topic's main category",
    "P1566": "GeoNames ID",
    # Identifier-related
    "P1630": "formatter URL",
    "P1793": "format as a regular expression",
    "P2302": "property constraint",
}


def fetch_property_data(property_ids: list[str]) -> dict:
    """Fetch property metadata from QLever."""
    if not property_ids:
        return {}

    values = " ".join([f"wd:{pid}" for pid in property_ids])

    query = f"""
    PREFIX wd: <http://www.wikidata.org/entity/>
    PREFIX wdt: <http://www.wikidata.org/prop/direct/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX schema: <http://schema.org/>

    SELECT ?prop ?propLabel ?description ?datatype WHERE {{
        VALUES ?prop {{ {values} }}

        OPTIONAL {{ ?prop rdfs:label ?propLabel . FILTER(LANG(?propLabel) = "en") }}
        OPTIONAL {{ ?prop schema:description ?description . FILTER(LANG(?description) = "en") }}
        OPTIONAL {{ ?prop wdt:P2302 ?datatype . }}
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
                    "property_name": binding.get("propLabel", {}).get("value"),
                    "description": binding.get("description", {}).get("value"),
                }

        return results

    except Exception as e:
        print(f"  Warning: Fetch failed: {e}")
        return {}


def main():
    if len(sys.argv) < 2:
        print("Usage: python 09_create_properties_table.py <database_path>")
        sys.exit(1)

    db_path = sys.argv[1]

    print("=" * 60)
    print("CREATE PROPERTIES DEFINITION TABLE")
    print("=" * 60)

    print("\n[1/4] Opening database...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    print(f"  Opened {db_path}")

    # Create table
    print("\n[2/4] Creating properties_definition table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS properties_definition (
            property_id TEXT PRIMARY KEY,
            property_name TEXT,
            used_for TEXT,
            description TEXT,
            wikidata_url TEXT
        )
    """)
    conn.commit()
    print("  Table created.")

    # Get all unique property IDs from identifiers table
    print("\n[3/4] Collecting property IDs...")
    cursor.execute("SELECT DISTINCT property_id FROM identifiers")
    identifier_props = {row[0] for row in cursor.fetchall() if row[0]}

    # Combine with known properties
    all_props = set(PROPERTIES.keys()) | identifier_props
    print(f"  Found {len(all_props)} unique properties")

    # Check which ones are already in the table
    cursor.execute("SELECT property_id FROM properties_definition")
    existing = {row[0] for row in cursor.fetchall()}
    to_fetch = list(all_props - existing)
    print(f"  {len(to_fetch)} properties to fetch")

    if not to_fetch:
        print("  Nothing to fetch!")
    else:
        # Fetch from QLever
        print("\n[4/4] Fetching property definitions from QLever...")

        # Batch fetch
        BATCH_SIZE = 100
        batches = [to_fetch[i : i + BATCH_SIZE] for i in range(0, len(to_fetch), BATCH_SIZE)]
        all_data = {}

        for batch in tqdm(batches, desc="  Fetching"):
            data = fetch_property_data(batch)
            all_data.update(data)
            time.sleep(0.1)

        # Insert into table
        print(f"\n  Inserting {len(to_fetch)} properties...")
        for prop_id in to_fetch:
            info = all_data.get(prop_id, {})
            used_for = PROPERTIES.get(prop_id, "identifier")
            cursor.execute(
                """
                INSERT OR REPLACE INTO properties_definition
                (property_id, property_name, used_for, description, wikidata_url)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    prop_id,
                    info.get("property_name"),
                    used_for,
                    info.get("description"),
                    f"https://www.wikidata.org/wiki/Property:{prop_id}",
                ),
            )
        conn.commit()

    # Show sample
    print("\n  Sample data:")
    print("  " + "-" * 100)
    cursor.execute(
        """
        SELECT property_id, property_name, used_for, substr(description, 1, 40)
        FROM properties_definition
        ORDER BY property_id
        LIMIT 15
        """
    )
    for row in cursor.fetchall():
        pid, name, used, desc = row
        print(f"  {pid:10} | {(name or '-')[:25]:25} | {(used or '-')[:15]:15} | {(desc or '-')[:35]}")
    print("  " + "-" * 100)

    # Stats
    cursor.execute("SELECT COUNT(*) FROM properties_definition")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM properties_definition WHERE description IS NOT NULL")
    with_desc = cursor.fetchone()[0]
    print(f"\n  {total} properties in table, {with_desc} with descriptions")

    conn.close()
    print("\n" + "=" * 60)
    print("DONE!")
    print("=" * 60)


if __name__ == "__main__":
    main()
