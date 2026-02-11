"""Extract writers (Q36180) using chunked Q-number ranges.

For very large occupations like writer (~680k), we break the query into
chunks by Q-number ranges to avoid SPARQL timeouts.
"""

import json
import os
import re
import time
import requests
from datetime import datetime
from tqdm import tqdm

# Paths
BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "extracted", "individuals")
OCCUPATION_DIR = os.path.join(OUTPUT_DIR, "occupation")
PROGRESS_FILE = os.path.join(OUTPUT_DIR, "writer_extraction_progress.json")

# Settings
OCCUPATION_ID = "Q36180"
OCCUPATION_NAME = "writer"
ENDPOINT = "https://query.wikidata.org/sparql"
HEADERS = {"Accept": "application/json", "User-Agent": "CulturaDatabase/1.0"}

# Chunk settings - Q-numbers go from Q1 to ~Q130M
# We'll use ranges of 1M Q-numbers per chunk
CHUNK_SIZE = 1_000_000
MAX_Q_NUMBER = 130_000_000
DELAY_BETWEEN_CHUNKS = 2


def log(msg):
    print(msg, flush=True)


def clean_json(s):
    """Remove control characters that break JSON parsing."""
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', s)


def load_progress():
    """Load progress from file."""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"completed_chunks": [], "results": [], "last_chunk_start": 0}


def save_progress(progress):
    """Save progress to file."""
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f)


def sparql_query(query: str, timeout: int = 180) -> list[dict] | None:
    """Execute SPARQL query with retries."""
    for attempt in range(3):
        try:
            response = requests.get(
                ENDPOINT,
                params={"query": query},
                headers=HEADERS,
                timeout=timeout
            )
            response.raise_for_status()
            cleaned = clean_json(response.text)
            data = json.loads(cleaned)
            return data["results"]["bindings"]
        except requests.exceptions.Timeout:
            if attempt < 2:
                wait = 30 * (attempt + 1)
                log(f"    Timeout (attempt {attempt+1}), retry in {wait}s...")
                time.sleep(wait)
            else:
                return None
        except Exception as e:
            if attempt < 2:
                wait = 30 * (attempt + 1)
                log(f"    Error: {str(e)[:50]}, retry in {wait}s...")
                time.sleep(wait)
            else:
                log(f"    Failed after 3 attempts: {str(e)[:80]}")
                return None
    return None


def fetch_chunk(start_q: int, end_q: int) -> list[dict]:
    """Fetch writers with Q-numbers in range [start_q, end_q)."""
    query = f"""
    SELECT ?item ?itemLabel WHERE {{
      ?item wdt:P106 wd:{OCCUPATION_ID} .
      FILTER(xsd:integer(SUBSTR(STR(?item), 33)) >= {start_q})
      FILTER(xsd:integer(SUBSTR(STR(?item), 33)) < {end_q})
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
    """

    results = sparql_query(query)
    if results is None:
        return []

    items = []
    for r in results:
        item_url = r.get("item", {}).get("value", "")
        wikidata_id = item_url.split("/")[-1] if item_url else ""
        if wikidata_id:
            items.append({
                "wikidata_id": wikidata_id,
                "name": r.get("itemLabel", {}).get("value", ""),
            })
    return items


def save_final_result(all_results):
    """Save final result to occupation file."""
    filepath = os.path.join(OCCUPATION_DIR, f"{OCCUPATION_ID}.json")
    data = {
        "occupation_id": OCCUPATION_ID,
        "occupation_name": OCCUPATION_NAME,
        "count": len(all_results),
        "results": all_results,
        "error": None,
    }
    with open(filepath, "w") as f:
        json.dump(data, f)
    log(f"\nSaved to {filepath}")


def main():
    log(f"Extracting {OCCUPATION_NAME} ({OCCUPATION_ID}) using chunked Q-number ranges")
    log(f"Chunk size: {CHUNK_SIZE:,} Q-numbers per query")

    progress = load_progress()
    all_results = progress["results"]
    completed_chunks = set(progress["completed_chunks"])

    if all_results:
        log(f"Resuming from progress: {len(all_results):,} already fetched")

    # Calculate total chunks
    total_chunks = MAX_Q_NUMBER // CHUNK_SIZE

    # Build list of chunks to process
    chunks_to_process = []
    for i in range(total_chunks):
        start_q = i * CHUNK_SIZE + 1
        if start_q not in completed_chunks:
            chunks_to_process.append(start_q)

    log(f"Chunks remaining: {len(chunks_to_process)} / {total_chunks}")

    start_time = datetime.now()

    for start_q in tqdm(chunks_to_process, desc="Processing chunks"):
        end_q = start_q + CHUNK_SIZE

        results = fetch_chunk(start_q, end_q)

        if results:
            all_results.extend(results)
            tqdm.write(f"  Q{start_q:,}-Q{end_q:,}: +{len(results):,} (total: {len(all_results):,})")

        # Mark chunk as completed and save progress
        completed_chunks.add(start_q)
        progress["completed_chunks"] = list(completed_chunks)
        progress["results"] = all_results
        progress["last_chunk_start"] = start_q
        save_progress(progress)

        time.sleep(DELAY_BETWEEN_CHUNKS)

    # Deduplicate results (in case of any overlap)
    seen = set()
    unique_results = []
    for r in all_results:
        if r["wikidata_id"] not in seen:
            seen.add(r["wikidata_id"])
            unique_results.append(r)

    duration = (datetime.now() - start_time).total_seconds()
    log(f"\nCompleted in {duration:.0f}s")
    log(f"Total unique writers: {len(unique_results):,}")

    # Save final result
    save_final_result(unique_results)

    # Clean up progress file
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
        log("Cleaned up progress file")


if __name__ == "__main__":
    main()
