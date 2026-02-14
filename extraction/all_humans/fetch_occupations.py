"""
Enrich occupations table with data from QLever:
- description_en: Description in English
- instance_of_id: Wikidata ID of instance type
- instance_of: Instance type name

Run: python 08_enrich_occupations.py ../../data/humans_clean.sqlite3
"""

import sqlite3
import requests
import sys
from tqdm import tqdm
import time

QLEVER_URL = "https://qlever.cs.uni-freiburg.de/api/wikidata"
BATCH_SIZE = 100


def fetch_occupation_data(occupation_ids: list[str]) -> dict:
    """Fetch description and instance_of for occupation IDs."""
    if not occupation_ids:
        return {}

    values = " ".join([f"wd:{oid}" for oid in occupation_ids if oid])

    query = f"""
    PREFIX wd: <http://www.wikidata.org/entity/>
    PREFIX wdt: <http://www.wikidata.org/prop/direct/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX schema: <http://schema.org/>

    SELECT ?occ ?description ?instance ?instanceLabel WHERE {{
        VALUES ?occ {{ {values} }}

        OPTIONAL {{ ?occ schema:description ?description . FILTER(LANG(?description) = "en") }}
        OPTIONAL {{
            ?occ wdt:P31 ?instance .
            ?instance rdfs:label ?instanceLabel . FILTER(LANG(?instanceLabel) = "en")
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
            occ_uri = binding.get("occ", {}).get("value", "")
            occ_id = occ_uri.split("/")[-1] if occ_uri else None
            if not occ_id:
                continue

            if occ_id not in results:
                results[occ_id] = {
                    "description_en": None,
                    "instance_of_id": None,
                    "instance_of": None,
                }

            if not results[occ_id]["description_en"]:
                results[occ_id]["description_en"] = binding.get("description", {}).get("value")

            if not results[occ_id]["instance_of"]:
                instance_uri = binding.get("instance", {}).get("value", "")
                results[occ_id]["instance_of_id"] = (
                    instance_uri.split("/")[-1] if instance_uri and "/Q" in instance_uri else None
                )
                results[occ_id]["instance_of"] = binding.get("instanceLabel", {}).get("value")

        return results

    except Exception as e:
        print(f"  Warning: Batch failed: {e}")
        return {}


def main():
    if len(sys.argv) < 2:
        print("Usage: python 08_enrich_occupations.py <database_path>")
        sys.exit(1)

    db_path = sys.argv[1]

    print("=" * 60)
    print("ENRICH OCCUPATIONS")
    print("=" * 60)

    print("\n[1/4] Opening database...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    print(f"  Opened {db_path}")

    # Add columns
    print("\n[2/4] Adding columns...")
    new_columns = [
        ("description_en", "TEXT"),
        ("instance_of_id", "TEXT"),
        ("instance_of", "TEXT"),
    ]

    for col_name, col_type in new_columns:
        try:
            cursor.execute(f"ALTER TABLE occupations ADD COLUMN {col_name} {col_type}")
            print(f"  Added column: {col_name}")
        except sqlite3.OperationalError:
            print(f"  Column exists: {col_name}")

    conn.commit()

    # Get occupation IDs
    print("\n[3/4] Getting occupations to enrich...")
    cursor.execute("SELECT id FROM occupations WHERE description_en IS NULL")
    occupation_ids = [row[0] for row in cursor.fetchall() if row[0]]
    print(f"  Found {len(occupation_ids)} occupations to enrich")

    if not occupation_ids:
        print("  Nothing to enrich!")
        conn.close()
        return

    # Fetch from QLever
    print("\n[4/4] Fetching from QLever...")
    n_batches = (len(occupation_ids) + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"  {n_batches} batches of {BATCH_SIZE}")

    total_updated = 0
    batches = [occupation_ids[i : i + BATCH_SIZE] for i in range(0, len(occupation_ids), BATCH_SIZE)]

    pbar = tqdm(batches, desc="  Fetching", unit="batch")
    for batch in pbar:
        data = fetch_occupation_data(batch)
        batch_updated = 0

        for occ_id, info in data.items():
            cursor.execute(
                """
                UPDATE occupations
                SET description_en = ?, instance_of_id = ?, instance_of = ?
                WHERE id = ?
                """,
                (info["description_en"], info["instance_of_id"], info["instance_of"], occ_id),
            )
            if cursor.rowcount > 0:
                batch_updated += 1
                total_updated += 1

        conn.commit()
        pbar.set_postfix({"updated": total_updated, "batch": batch_updated})
        time.sleep(0.1)

    print(f"\n  Updated {total_updated} occupations")

    # Show sample
    print("\n  Sample data:")
    print("  " + "-" * 100)
    cursor.execute(
        """
        SELECT id, name_en, instance_of, substr(description_en, 1, 35), count
        FROM occupations
        WHERE description_en IS NOT NULL
        ORDER BY count DESC
        LIMIT 10
        """
    )
    for row in cursor.fetchall():
        oid, name, inst, desc, count = row
        print(f"  {oid:12} | {name[:20]:20} | {inst or '-':20} | {count:6}")
    print("  " + "-" * 100)

    # Stats
    cursor.execute("SELECT COUNT(*) FROM occupations WHERE description_en IS NOT NULL")
    with_desc = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM occupations")
    total = cursor.fetchone()[0]
    print(f"\n  {with_desc}/{total} occupations have description ({100*with_desc/total:.1f}%)")

    conn.close()
    print("\n" + "=" * 60)
    print("DONE!")
    print("=" * 60)


if __name__ == "__main__":
    main()
