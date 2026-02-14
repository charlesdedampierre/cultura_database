"""
Enrich nationalities table with data from QLever:
- wikidata_id: The Q identifier
- description_en: Description in English
- instance_of: What type of entity (country, historical country, etc.)

Run: python 06_enrich_nationalities.py ../../data/humans_clean.sqlite3
"""

import sqlite3
import requests
import sys
from tqdm import tqdm
import time

QLEVER_URL = "https://qlever.cs.uni-freiburg.de/api/wikidata"
BATCH_SIZE = 50


def fetch_nationality_data(names: list[str]) -> dict:
    """Fetch wikidata_id, description, instance_of for nationality names."""
    if not names:
        return {}

    # Escape quotes in names and create VALUES clause
    escaped = [n.replace('"', '\\"') for n in names]
    values = " ".join([f'"{n}"@en' for n in escaped])

    query = f"""
    PREFIX wd: <http://www.wikidata.org/entity/>
    PREFIX wdt: <http://www.wikidata.org/prop/direct/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX schema: <http://schema.org/>

    SELECT ?name ?entity ?description ?instanceLabel WHERE {{
        VALUES ?name {{ {values} }}

        ?entity rdfs:label ?name .
        ?entity wdt:P31 ?instance .

        # Filter for countries/territories
        VALUES ?instance {{
            wd:Q6256 wd:Q3024240 wd:Q3624078 wd:Q1763527 wd:Q1151405
            wd:Q15634554 wd:Q185441 wd:Q123480 wd:Q112099 wd:Q1250464
            wd:Q7275 wd:Q788561 wd:Q17376908
        }}

        OPTIONAL {{ ?entity schema:description ?description . FILTER(LANG(?description) = "en") }}
        OPTIONAL {{ ?instance rdfs:label ?instanceLabel . FILTER(LANG(?instanceLabel) = "en") }}
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
            name = binding.get("name", {}).get("value", "")
            if not name:
                continue

            entity_uri = binding.get("entity", {}).get("value", "")
            wikidata_id = entity_uri.split("/")[-1] if entity_uri and "/Q" in entity_uri else None

            if name not in results and wikidata_id:
                results[name] = {
                    "wikidata_id": wikidata_id,
                    "description_en": binding.get("description", {}).get("value"),
                    "instance_of": binding.get("instanceLabel", {}).get("value"),
                }

        return results

    except Exception as e:
        print(f"  Warning: Batch failed: {e}")
        return {}


def main():
    if len(sys.argv) < 2:
        print("Usage: python 06_enrich_nationalities.py <database_path>")
        sys.exit(1)

    db_path = sys.argv[1]

    print("=" * 60)
    print("ENRICH NATIONALITIES")
    print("=" * 60)

    print("\n[1/4] Opening database...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    print(f"  Opened {db_path}")

    # Add columns
    print("\n[2/4] Adding columns...")
    new_columns = [
        ("wikidata_id", "TEXT"),
        ("description_en", "TEXT"),
        ("instance_of", "TEXT"),
    ]

    for col_name, col_type in new_columns:
        try:
            cursor.execute(f"ALTER TABLE nationalities ADD COLUMN {col_name} {col_type}")
            print(f"  Added column: {col_name}")
        except sqlite3.OperationalError:
            print(f"  Column exists: {col_name}")

    conn.commit()

    # Get nationalities to enrich
    print("\n[3/4] Getting nationalities to enrich...")
    cursor.execute("SELECT name_en FROM nationalities WHERE wikidata_id IS NULL ORDER BY count DESC")
    names = [row[0] for row in cursor.fetchall()]
    print(f"  Found {len(names)} nationalities to enrich")

    if not names:
        print("  Nothing to enrich!")
        conn.close()
        return

    # Fetch from QLever
    print("\n[4/4] Fetching from QLever...")
    n_batches = (len(names) + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"  {n_batches} batches of {BATCH_SIZE}")

    total_updated = 0
    batches = [names[i : i + BATCH_SIZE] for i in range(0, len(names), BATCH_SIZE)]

    pbar = tqdm(batches, desc="  Fetching", unit="batch")
    for batch in pbar:
        data = fetch_nationality_data(batch)
        batch_updated = 0

        for name, info in data.items():
            cursor.execute(
                """
                UPDATE nationalities
                SET wikidata_id = ?, description_en = ?, instance_of = ?
                WHERE name_en = ?
                """,
                (info["wikidata_id"], info["description_en"], info["instance_of"], name),
            )
            if cursor.rowcount > 0:
                batch_updated += 1
                total_updated += 1

        conn.commit()
        pbar.set_postfix({"updated": total_updated, "batch": batch_updated})
        time.sleep(0.1)

    print(f"\n  Updated {total_updated} nationalities")

    # Show sample
    print("\n  Sample data:")
    print("  " + "-" * 90)
    cursor.execute(
        """
        SELECT name_en, wikidata_id, instance_of, substr(description_en, 1, 40), count
        FROM nationalities
        WHERE wikidata_id IS NOT NULL
        ORDER BY count DESC
        LIMIT 10
        """
    )
    for row in cursor.fetchall():
        name, qid, inst, desc, count = row
        print(f"  {name[:20]:20} | {qid or '-':12} | {inst or '-':20} | {count:6}")
    print("  " + "-" * 90)

    # Stats
    cursor.execute("SELECT COUNT(*) FROM nationalities WHERE wikidata_id IS NOT NULL")
    with_id = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM nationalities")
    total = cursor.fetchone()[0]
    print(f"\n  {with_id}/{total} nationalities have wikidata_id ({100*with_id/total:.1f}%)")

    conn.close()
    print("\n" + "=" * 60)
    print("DONE!")
    print("=" * 60)


if __name__ == "__main__":
    main()
