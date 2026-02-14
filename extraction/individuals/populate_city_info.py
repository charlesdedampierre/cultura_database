"""
Populate city info - ONE property at a time, batched.
"""

import os
import sqlite3
import sys
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from wikidata_api import sparql_query, set_endpoint

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"

PREFIXES = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
"""

DB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "sample", "individuals_qlever_sample.db"
)

BATCH_SIZE = 500


def get_city_ids_needing_update(column: str) -> list:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(f"SELECT wikidata_id FROM SAMPLE_cities WHERE {column} IS NULL")
    ids = [r[0] for r in cur.fetchall()]
    conn.close()
    return ids


def fetch_and_update(prop: str, id_col: str, name_col: str, city_ids: list):
    """Fetch property and update DB."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    for i in tqdm(range(0, len(city_ids), BATCH_SIZE), desc=f"  {name_col}", leave=False):
        batch = city_ids[i:i+BATCH_SIZE]
        values = " ".join([f"wd:{cid}" for cid in batch])

        query = PREFIXES + f"""
        SELECT ?city ?val ?valLabel WHERE {{
          VALUES ?city {{ {values} }}
          ?city wdt:{prop} ?val.
          OPTIONAL {{ ?val rdfs:label ?valLabel. FILTER(LANG(?valLabel) = 'en') }}
        }}
        """

        try:
            rows = sparql_query(query)
            seen = set()
            for row in rows:
                cid = row.get("city", "").split("/")[-1]
                if cid and cid not in seen:
                    seen.add(cid)
                    val = row.get("val", "")
                    val_id = val.split("/")[-1] if "/" in val else val
                    val_name = row.get("valLabel", "")
                    cur.execute(f"UPDATE SAMPLE_cities SET {id_col} = ?, {name_col} = ? WHERE wikidata_id = ?",
                               (val_id, val_name, cid))
        except Exception as e:
            print(f"Error: {e}")

        conn.commit()

    conn.close()


def fetch_coords(city_ids: list):
    """Fetch coordinates."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    for i in tqdm(range(0, len(city_ids), BATCH_SIZE), desc="  coordinates", leave=False):
        batch = city_ids[i:i+BATCH_SIZE]
        values = " ".join([f"wd:{cid}" for cid in batch])

        query = PREFIXES + f"""
        SELECT ?city ?val WHERE {{
          VALUES ?city {{ {values} }}
          ?city wdt:P625 ?val.
        }}
        """

        try:
            rows = sparql_query(query)
            seen = set()
            for row in rows:
                cid = row.get("city", "").split("/")[-1]
                if cid and cid not in seen:
                    seen.add(cid)
                    cur.execute("UPDATE SAMPLE_cities SET coordinates = ? WHERE wikidata_id = ?",
                               (row.get("val", ""), cid))
        except Exception as e:
            print(f"Error: {e}")

        conn.commit()

    conn.close()


def main():
    print("City Info Extractor")
    set_endpoint(QLEVER_ENDPOINT)

    # Get cities needing updates
    city_ids = get_city_ids_needing_update("country_id")
    print(f"Cities needing country: {len(city_ids)}")

    if city_ids:
        print("1/4 Countries (P17)...")
        fetch_and_update("P17", "country_id", "country_name", city_ids)

    city_ids = get_city_ids_needing_update("coordinates")
    if city_ids:
        print("2/4 Coordinates (P625)...")
        fetch_coords(city_ids)

    city_ids = get_city_ids_needing_update("instance_of_id")
    if city_ids:
        print("3/4 Instance of (P31)...")
        fetch_and_update("P31", "instance_of_id", "instance_of", city_ids)

    # Modern country
    city_ids = get_city_ids_needing_update("modern_country_id")
    if city_ids:
        print("4/4 Modern countries...")
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        for i in tqdm(range(0, len(city_ids), BATCH_SIZE), desc="  modern_country", leave=False):
            batch = city_ids[i:i+BATCH_SIZE]
            values = " ".join([f"wd:{cid}" for cid in batch])
            query = PREFIXES + f"""
            SELECT ?city ?country ?countryLabel WHERE {{
              VALUES ?city {{ {values} }}
              ?city wdt:P17 ?country.
              ?country wdt:P31 wd:Q3624078.
              OPTIONAL {{ ?country rdfs:label ?countryLabel. FILTER(LANG(?countryLabel) = 'en') }}
            }}
            """
            try:
                rows = sparql_query(query)
                seen = set()
                for row in rows:
                    cid = row.get("city", "").split("/")[-1]
                    if cid and cid not in seen:
                        seen.add(cid)
                        cur.execute("UPDATE SAMPLE_cities SET modern_country_id = ?, modern_country_name = ? WHERE wikidata_id = ?",
                                   (row.get("country", "").split("/")[-1], row.get("countryLabel", ""), cid))
            except Exception as e:
                print(f"Error: {e}")
            conn.commit()
        conn.close()

    # Summary
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT COUNT(*), COUNT(country_id), COUNT(coordinates), COUNT(instance_of_id), COUNT(modern_country_id) FROM SAMPLE_cities")
    total, c1, c2, c3, c4 = cur.fetchone()
    print(f"\nTotal: {total} cities")
    print(f"  with country: {c1}")
    print(f"  with coords: {c2}")
    print(f"  with instance: {c3}")
    print(f"  with modern_country: {c4}")
    conn.close()


if __name__ == "__main__":
    main()
