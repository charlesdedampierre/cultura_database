"""
Extract sitelinks for ALL individuals from Wikidata using QLever endpoint in bulk batches.

Features:
- Bulk queries (500 IDs per query) for efficiency
- Threading for parallel batch processing
- Progress bar with tqdm
- Resume support via checkpoint file
- JSON output to data/all_humans/

Output:
- data/all_humans/all_human_sitelinks.json
"""

import json
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import requests
from tqdm import tqdm

# QLever endpoint
QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"

# SPARQL Prefixes
PREFIXES = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX schema: <http://schema.org/>
"""

# Configuration
BATCH_SIZE = 500  # IDs per SPARQL query
NUM_THREADS = 10  # Parallel queries
SAVE_EVERY = 500000  # Save JSON every N individuals

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "humans_clean.sqlite3")
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "all_humans")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "all_human_sitelinks.json")
CHECKPOINT_FILE = os.path.join(OUTPUT_DIR, "sitelinks_checkpoint.json")

# Thread-safe locks
data_lock = Lock()
checkpoint_lock = Lock()


def sparql_query(query: str, retries: int = 3) -> list:
    """Execute SPARQL query on QLever endpoint."""
    for attempt in range(retries):
        try:
            response = requests.post(
                QLEVER_ENDPOINT,
                data={"query": query},
                headers={"Accept": "application/sparql-results+json"},
                timeout=120
            )
            response.raise_for_status()
            data = response.json()

            results = []
            if "results" in data and "bindings" in data["results"]:
                for binding in data["results"]["bindings"]:
                    row = {}
                    for key, val in binding.items():
                        row[key] = val.get("value", "")
                    results.append(row)
            return results
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise e
    return []


def get_sitelinks_batch(wiki_ids: list) -> list:
    """Get sitelinks for a batch of individuals."""
    if not wiki_ids:
        return []

    # Build VALUES clause
    values = " ".join([f"wd:{wid}" for wid in wiki_ids])

    query = PREFIXES + f"""
    SELECT ?person ?sitelink ?siteName WHERE {{
      VALUES ?person {{ {values} }}
      ?sitelink schema:about ?person .
      ?sitelink schema:name ?siteName .
    }}
    """

    try:
        rows = sparql_query(query)
        results = []
        for row in rows:
            person_url = row.get("person", "")
            wikidata_id = person_url.split("/")[-1] if "/" in person_url else ""
            url = row.get("sitelink", "")
            title = row.get("siteName", "")

            # Extract site from URL (e.g., "en.wikipedia.org")
            site = ""
            if "//" in url:
                site = url.split("//")[1].split("/")[0]

            if wikidata_id and url:
                results.append({
                    "wikidata_id": wikidata_id,
                    "site": site,
                    "title": title,
                    "url": url
                })
        return results
    except Exception as e:
        print(f"Error in batch query: {e}")
        return []


def load_checkpoint() -> tuple[set, dict]:
    """Load processed IDs and partial data from checkpoint."""
    processed_ids = set()
    all_sitelinks = {}

    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r") as f:
            processed_ids = set(json.load(f))

    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r") as f:
            all_sitelinks = json.load(f)

    return processed_ids, all_sitelinks


def save_checkpoint(processed_ids: set):
    """Save processed IDs to checkpoint."""
    with checkpoint_lock:
        with open(CHECKPOINT_FILE, "w") as f:
            json.dump(list(processed_ids), f)


def save_sitelinks(all_sitelinks: dict):
    """Save all sitelinks to JSON file."""
    with data_lock:
        with open(OUTPUT_FILE, "w") as f:
            json.dump(all_sitelinks, f)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Database: {DB_PATH}")
    print(f"Output: {OUTPUT_FILE}")
    print(f"QLever endpoint: {QLEVER_ENDPOINT}")

    # Connect to database to get IDs
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("Loading individual IDs...")
    cursor.execute("SELECT wikidata_id FROM individuals")
    all_ids = [row[0] for row in cursor.fetchall()]
    total = len(all_ids)
    print(f"Total individuals: {total:,}")
    conn.close()

    # Load checkpoint and existing data
    processed_ids, all_sitelinks = load_checkpoint()
    if processed_ids:
        print(f"Resuming from checkpoint: {len(processed_ids):,} already processed")
        print(f"Existing sitelinks data for: {len(all_sitelinks):,} individuals")

    # Filter to remaining IDs
    remaining_ids = [wid for wid in all_ids if wid not in processed_ids]
    print(f"Remaining to process: {len(remaining_ids):,}")

    if not remaining_ids:
        print("All individuals already processed!")
        return

    # Create batches
    batches = [remaining_ids[i:i+BATCH_SIZE] for i in range(0, len(remaining_ids), BATCH_SIZE)]
    print(f"Total batches: {len(batches):,} (size: {BATCH_SIZE})")

    # Process with threading
    start_time = time.time()
    total_sitelinks = 0
    processed_count = len(processed_ids)

    print(f"\nStarting extraction with {NUM_THREADS} threads...")

    with tqdm(total=len(remaining_ids), desc="Extracting sitelinks", unit="individuals") as pbar:
        with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
            future_to_batch = {executor.submit(get_sitelinks_batch, batch): batch for batch in batches}

            for future in as_completed(future_to_batch):
                batch = future_to_batch[future]
                try:
                    sitelinks = future.result()

                    # Group sitelinks by wikidata_id
                    with data_lock:
                        for sl in sitelinks:
                            wid = sl["wikidata_id"]
                            if wid not in all_sitelinks:
                                all_sitelinks[wid] = []
                            all_sitelinks[wid].append({
                                "site": sl["site"],
                                "title": sl["title"],
                                "url": sl["url"]
                            })

                    # Update tracking
                    for wid in batch:
                        processed_ids.add(wid)

                    total_sitelinks += len(sitelinks)
                    processed_count += len(batch)
                    pbar.update(len(batch))

                    # Save periodically
                    if processed_count % SAVE_EVERY < BATCH_SIZE:
                        save_sitelinks(all_sitelinks)
                        save_checkpoint(processed_ids)
                        tqdm.write(f"  [Saved checkpoint at {processed_count:,}]")

                except Exception as e:
                    tqdm.write(f"Batch error: {e}")
                    pbar.update(len(batch))

    # Final save
    save_sitelinks(all_sitelinks)
    save_checkpoint(processed_ids)

    # Stats
    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print("EXTRACTION COMPLETE")
    print(f"{'='*60}")
    print(f"Processed: {len(remaining_ids):,} individuals")
    print(f"Total sitelinks extracted: {total_sitelinks:,}")
    print(f"Unique individuals with sitelinks: {len(all_sitelinks):,}")
    print(f"Time: {elapsed/3600:.2f} hours ({elapsed:.0f} seconds)")
    print(f"Rate: {len(remaining_ids)/elapsed:.1f} individuals/sec")
    print(f"\nOutput saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
