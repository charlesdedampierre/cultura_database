"""
Bulk fetch ALL sitelinks from QLever using a single query.
Much faster than individual fetches.

Run: python 10_fetch_sitelinks_bulk.py ../../data/humans_clean.sqlite3
"""

import sqlite3
import requests
import sys
from tqdm import tqdm
import time

QLEVER_URL = "https://qlever.cs.uni-freiburg.de/api/wikidata"


def fetch_all_sitelinks_for_humans(db_path: str):
    """Fetch all sitelinks for humans in the database using bulk QLever query."""

    print("=" * 60)
    print("BULK FETCH SITELINKS FROM QLEVER")
    print("=" * 60)

    print("\n[1/5] Opening database...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    print(f"  Opened {db_path}")

    # Create table
    print("\n[2/5] Creating sitelinks table...")
    cursor.execute("DROP TABLE IF EXISTS sitelinks")
    cursor.execute("""
        CREATE TABLE sitelinks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wikidata_id TEXT NOT NULL,
            name TEXT,
            site TEXT,
            title TEXT,
            url TEXT
        )
    """)
    conn.commit()
    print("  Table created.")

    # Get all wikidata_ids from individuals
    print("\n[3/5] Getting individuals with sitelinks...")
    cursor.execute("SELECT wikidata_id, name_en FROM individuals WHERE sitelinks_count > 0")
    individuals = {row[0]: row[1] for row in cursor.fetchall()}
    print(f"  Found {len(individuals)} individuals with sitelinks")

    # Bulk query - fetch sitelinks for ALL humans at once
    print("\n[4/5] Fetching ALL sitelinks from QLever (bulk query)...")
    print("  This query fetches all Wikipedia links for humans...")

    query = """
    PREFIX wd: <http://www.wikidata.org/entity/>
    PREFIX wdt: <http://www.wikidata.org/prop/direct/>
    PREFIX schema: <http://schema.org/>

    SELECT ?human ?sitelink ?title ?wiki WHERE {
        ?human wdt:P31 wd:Q5 .
        ?sitelink schema:about ?human .
        ?sitelink schema:isPartOf ?wiki .
        ?sitelink schema:name ?title .
    }
    """

    try:
        print("  Sending query to QLever...")
        response = requests.get(
            QLEVER_URL,
            params={"query": query},
            headers={"Accept": "application/json", "User-Agent": "CulturaDatabase/1.0"},
            timeout=600,  # 10 min timeout for large query
            stream=True
        )
        response.raise_for_status()

        print("  Parsing response...")
        data = response.json()
        bindings = data.get("results", {}).get("bindings", [])
        print(f"  Got {len(bindings)} sitelinks from QLever")

    except Exception as e:
        print(f"  Error: {e}")
        print("  Trying paginated approach instead...")
        bindings = fetch_paginated(individuals)

    # Insert into database
    print("\n[5/5] Inserting sitelinks into database...")
    inserted = 0
    batch = []
    batch_size = 10000

    for binding in tqdm(bindings, desc="  Processing"):
        human_uri = binding.get("human", {}).get("value", "")
        wikidata_id = human_uri.split("/")[-1] if human_uri else None

        if not wikidata_id or wikidata_id not in individuals:
            continue

        sitelink_url = binding.get("sitelink", {}).get("value", "")
        wiki_url = binding.get("wiki", {}).get("value", "")
        site = wiki_url.replace("https://", "").rstrip("/") if wiki_url else None
        title = binding.get("title", {}).get("value")
        name = individuals.get(wikidata_id)

        batch.append((wikidata_id, name, site, title, sitelink_url))

        if len(batch) >= batch_size:
            cursor.executemany(
                "INSERT INTO sitelinks (wikidata_id, name, site, title, url) VALUES (?, ?, ?, ?, ?)",
                batch
            )
            conn.commit()
            inserted += len(batch)
            batch = []

    # Insert remaining
    if batch:
        cursor.executemany(
            "INSERT INTO sitelinks (wikidata_id, name, site, title, url) VALUES (?, ?, ?, ?, ?)",
            batch
        )
        conn.commit()
        inserted += len(batch)

    # Create index
    print("  Creating index...")
    cursor.execute("CREATE INDEX idx_sitelinks_wikidata ON sitelinks(wikidata_id)")
    conn.commit()

    print(f"\n  Inserted {inserted} sitelinks")

    # Stats
    cursor.execute("SELECT COUNT(DISTINCT wikidata_id) FROM sitelinks")
    unique_ids = cursor.fetchone()[0]
    print(f"  Covering {unique_ids} individuals")

    # Sample
    print("\n  Sample data:")
    print("  " + "-" * 90)
    cursor.execute("""
        SELECT wikidata_id, name, site, title
        FROM sitelinks
        ORDER BY RANDOM()
        LIMIT 10
    """)
    for row in cursor.fetchall():
        qid, name, site, title = row
        print(f"  {qid:12} | {(name or '-')[:20]:20} | {(site or '-')[:25]:25} | {(title or '-')[:20]}")
    print("  " + "-" * 90)

    conn.close()
    print("\n" + "=" * 60)
    print("DONE!")
    print("=" * 60)


def fetch_paginated(individuals: dict) -> list:
    """Fallback: fetch in pages using OFFSET/LIMIT."""
    all_bindings = []
    page_size = 1000000
    offset = 0

    while True:
        query = f"""
        PREFIX wd: <http://www.wikidata.org/entity/>
        PREFIX wdt: <http://www.wikidata.org/prop/direct/>
        PREFIX schema: <http://schema.org/>

        SELECT ?human ?sitelink ?title ?wiki WHERE {{
            ?human wdt:P31 wd:Q5 .
            ?sitelink schema:about ?human .
            ?sitelink schema:isPartOf ?wiki .
            ?sitelink schema:name ?title .
        }}
        LIMIT {page_size}
        OFFSET {offset}
        """

        print(f"  Fetching page at offset {offset}...")
        try:
            response = requests.get(
                QLEVER_URL,
                params={"query": query},
                headers={"Accept": "application/json", "User-Agent": "CulturaDatabase/1.0"},
                timeout=300,
            )
            response.raise_for_status()
            data = response.json()
            bindings = data.get("results", {}).get("bindings", [])

            if not bindings:
                break

            all_bindings.extend(bindings)
            print(f"    Got {len(bindings)} results, total: {len(all_bindings)}")

            if len(bindings) < page_size:
                break

            offset += page_size
            time.sleep(1)

        except Exception as e:
            print(f"  Error at offset {offset}: {e}")
            break

    return all_bindings


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python 10_fetch_sitelinks_bulk.py <database_path>")
        sys.exit(1)

    fetch_all_sitelinks_for_humans(sys.argv[1])
