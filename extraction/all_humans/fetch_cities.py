"""
Enrich cities table with country data from QLever:
- iso_a3: ISO 3166-1 alpha-3 country code
- continent_id: Wikidata ID of continent
- continent: Continent name

Run: python 07_enrich_cities.py ../../data/humans_clean.sqlite3
"""

import sqlite3
import requests
import sys
from tqdm import tqdm
import time

QLEVER_URL = "https://qlever.cs.uni-freiburg.de/api/wikidata"
BATCH_SIZE = 100


def fetch_country_data(country_ids: list[str]) -> dict:
    """Fetch iso_a3 and continent for country IDs."""
    if not country_ids:
        return {}

    values = " ".join([f"wd:{cid}" for cid in country_ids if cid])

    query = f"""
    PREFIX wd: <http://www.wikidata.org/entity/>
    PREFIX wdt: <http://www.wikidata.org/prop/direct/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

    SELECT ?country ?iso_a3 ?continent ?continentLabel WHERE {{
        VALUES ?country {{ {values} }}

        OPTIONAL {{ ?country wdt:P298 ?iso_a3 . }}
        OPTIONAL {{
            ?country wdt:P30 ?continent .
            ?continent rdfs:label ?continentLabel . FILTER(LANG(?continentLabel) = "en")
        }}
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
            country_uri = binding.get("country", {}).get("value", "")
            country_id = country_uri.split("/")[-1] if country_uri else None
            if not country_id:
                continue

            if country_id not in results:
                results[country_id] = {
                    "iso_a3": None,
                    "continent_id": None,
                    "continent": None,
                }

            if not results[country_id]["iso_a3"]:
                results[country_id]["iso_a3"] = binding.get("iso_a3", {}).get("value")

            if not results[country_id]["continent"]:
                continent_uri = binding.get("continent", {}).get("value", "")
                results[country_id]["continent_id"] = (
                    continent_uri.split("/")[-1] if continent_uri and "/Q" in continent_uri else None
                )
                results[country_id]["continent"] = binding.get("continentLabel", {}).get("value")

        return results

    except Exception as e:
        print(f"  Warning: Batch failed: {e}")
        return {}


def main():
    if len(sys.argv) < 2:
        print("Usage: python 07_enrich_cities.py <database_path>")
        sys.exit(1)

    db_path = sys.argv[1]

    print("=" * 60)
    print("ENRICH CITIES WITH COUNTRY DATA")
    print("=" * 60)

    print("\n[1/4] Opening database...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    print(f"  Opened {db_path}")

    # Add columns
    print("\n[2/4] Adding columns...")
    new_columns = [
        ("iso_a3", "TEXT"),
        ("continent_id", "TEXT"),
        ("continent", "TEXT"),
    ]

    for col_name, col_type in new_columns:
        try:
            cursor.execute(f"ALTER TABLE cities ADD COLUMN {col_name} {col_type}")
            print(f"  Added column: {col_name}")
        except sqlite3.OperationalError:
            print(f"  Column exists: {col_name}")

    conn.commit()

    # Get unique country IDs
    print("\n[3/4] Getting unique countries...")
    cursor.execute("SELECT DISTINCT country_id FROM cities WHERE country_id IS NOT NULL AND iso_a3 IS NULL")
    country_ids = [row[0] for row in cursor.fetchall() if row[0]]
    print(f"  Found {len(country_ids)} unique countries to enrich")

    if not country_ids:
        print("  Nothing to enrich!")
        conn.close()
        return

    # Fetch from QLever
    print("\n[4/4] Fetching from QLever...")
    n_batches = (len(country_ids) + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"  {n_batches} batches of {BATCH_SIZE}")

    # Build country data map
    country_data = {}
    batches = [country_ids[i : i + BATCH_SIZE] for i in range(0, len(country_ids), BATCH_SIZE)]

    pbar = tqdm(batches, desc="  Fetching", unit="batch")
    for batch in pbar:
        data = fetch_country_data(batch)
        country_data.update(data)
        pbar.set_postfix({"countries": len(country_data)})
        time.sleep(0.1)

    print(f"\n  Fetched data for {len(country_data)} countries")

    # Update cities
    print("  Updating cities...")
    total_updated = 0
    for country_id, info in tqdm(country_data.items(), desc="  Updating"):
        cursor.execute(
            """
            UPDATE cities
            SET iso_a3 = ?, continent_id = ?, continent = ?
            WHERE country_id = ?
            """,
            (info["iso_a3"], info["continent_id"], info["continent"], country_id),
        )
        total_updated += cursor.rowcount

    conn.commit()
    print(f"  Updated {total_updated} cities")

    # Show sample
    print("\n  Sample data:")
    print("  " + "-" * 100)
    cursor.execute(
        """
        SELECT name_en, country_name, iso_a3, continent, count
        FROM cities
        WHERE iso_a3 IS NOT NULL
        ORDER BY count DESC
        LIMIT 10
        """
    )
    for row in cursor.fetchall():
        name, country, iso, cont, count = row
        print(f"  {name[:25]:25} | {country or '-':20} | {iso or '-':5} | {cont or '-':15} | {count:6}")
    print("  " + "-" * 100)

    # Stats
    cursor.execute("SELECT COUNT(*) FROM cities WHERE iso_a3 IS NOT NULL")
    with_iso = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM cities")
    total = cursor.fetchone()[0]
    print(f"\n  {with_iso}/{total} cities have iso_a3 ({100*with_iso/total:.1f}%)")

    conn.close()
    print("\n" + "=" * 60)
    print("DONE!")
    print("=" * 60)


if __name__ == "__main__":
    main()
