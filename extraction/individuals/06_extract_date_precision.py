"""
Extract date precision (birthdate & deathdate) for ALL individuals from Wikidata using QLever.

Precision values:
- 11 = day (exact date)
- 10 = month
- 9 = year only (01-01 is placeholder)
- 8 = decade
- 7 = century

Features:
- Threading with 15 workers
- Batch queries (50 IDs per query for efficiency)
- Checkpointing every 10,000 individuals
- Resume from last checkpoint
- Progress logging to txt file
- Final report of failures

Output:
- data/extracted/individuals_qlever/date_precision/batch_XXXX.json
- data/extracted/individuals_qlever/date_precision/extraction_progress.txt
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from threading import Lock
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from wikidata_api import sparql_query, set_endpoint

# QLever endpoint
QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"

# SPARQL Prefixes
PREFIXES = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX psv: <http://www.wikidata.org/prop/statement/value/>
PREFIX wikibase: <http://wikiba.se/ontology#>
"""

# Configuration
NUM_THREADS = 15
QUERY_BATCH_SIZE = 100  # IDs per SPARQL query (optimal based on speed test)
CHECKPOINT_EVERY = 10000
TEST_LIMIT = None  # Set to a number for testing

OUTPUT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "extracted", "individuals_qlever", "date_precision"
)
JSON_DIR = os.path.join(OUTPUT_DIR, "json_batches")
PROGRESS_FILE = os.path.join(OUTPUT_DIR, "extraction_progress.txt")
PROCESSED_IDS_FILE = os.path.join(OUTPUT_DIR, "processed_ids.json")

# Thread-safe
results_lock = Lock()
progress_lock = Lock()


def log_progress(message: str):
    """Log progress to file and console."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}"
    print(log_line)
    with progress_lock:
        with open(PROGRESS_FILE, "a") as f:
            f.write(log_line + "\n")


def get_processed_ids() -> set:
    """Get set of already processed IDs."""
    if not os.path.exists(PROCESSED_IDS_FILE):
        return set()
    with open(PROCESSED_IDS_FILE, "r") as f:
        return set(json.load(f))


def save_processed_ids(processed_ids: set):
    """Save processed IDs."""
    with open(PROCESSED_IDS_FILE, "w") as f:
        json.dump(list(processed_ids), f)


def save_batch_to_json(results: list, batch_num: int):
    """Save a batch of results to JSON."""
    os.makedirs(JSON_DIR, exist_ok=True)
    batch_file = os.path.join(JSON_DIR, f"batch_{batch_num:04d}.json")
    with open(batch_file, "w") as f:
        json.dump(results, f)
    return batch_file


def get_date_precision_batch(wiki_ids: list) -> list:
    """Get date precision for a batch of IDs using a single SPARQL query."""

    # Build VALUES clause
    values = " ".join([f"wd:{qid}" for qid in wiki_ids])

    query = PREFIXES + f"""
    SELECT ?person ?birthdate ?birthPrecision ?deathdate ?deathPrecision
    WHERE {{
      VALUES ?person {{ {values} }}
      OPTIONAL {{
        ?person p:P569 ?birthStmt.
        ?birthStmt psv:P569 ?birthVal.
        ?birthVal wikibase:timeValue ?birthdate.
        ?birthVal wikibase:timePrecision ?birthPrecision.
      }}
      OPTIONAL {{
        ?person p:P570 ?deathStmt.
        ?deathStmt psv:P570 ?deathVal.
        ?deathVal wikibase:timeValue ?deathdate.
        ?deathVal wikibase:timePrecision ?deathPrecision.
      }}
    }}
    """

    try:
        rows = sparql_query(query)

        # Group by person (may have multiple rows per person due to multiple dates)
        results_by_id = {}
        for row in rows:
            person_uri = row.get("person", "")
            qid = person_uri.split("/")[-1] if "/" in person_uri else person_uri

            if qid not in results_by_id:
                results_by_id[qid] = {
                    "wikidata_id": qid,
                    "birthdates": [],
                    "deathdates": []
                }

            # Add birthdate with precision
            if row.get("birthdate") and row.get("birthPrecision"):
                bd_entry = {
                    "date": row["birthdate"],
                    "precision": int(row["birthPrecision"])
                }
                if bd_entry not in results_by_id[qid]["birthdates"]:
                    results_by_id[qid]["birthdates"].append(bd_entry)

            # Add deathdate with precision
            if row.get("deathdate") and row.get("deathPrecision"):
                dd_entry = {
                    "date": row["deathdate"],
                    "precision": int(row["deathPrecision"])
                }
                if dd_entry not in results_by_id[qid]["deathdates"]:
                    results_by_id[qid]["deathdates"].append(dd_entry)

        # Build final results, including IDs with no dates
        results = []
        for qid in wiki_ids:
            if qid in results_by_id:
                data = results_by_id[qid]
                # Pick the most precise date if multiple exist
                birthdate = None
                birthdate_precision = None
                if data["birthdates"]:
                    best = max(data["birthdates"], key=lambda x: x["precision"])
                    birthdate = best["date"]
                    birthdate_precision = best["precision"]

                deathdate = None
                deathdate_precision = None
                if data["deathdates"]:
                    best = max(data["deathdates"], key=lambda x: x["precision"])
                    deathdate = best["date"]
                    deathdate_precision = best["precision"]

                results.append({
                    "wikidata_id": qid,
                    "birthdate": birthdate,
                    "birthdate_precision": birthdate_precision,
                    "deathdate": deathdate,
                    "deathdate_precision": deathdate_precision
                })
            else:
                results.append({
                    "wikidata_id": qid,
                    "birthdate": None,
                    "birthdate_precision": None,
                    "deathdate": None,
                    "deathdate_precision": None
                })

        return results

    except Exception as e:
        # Return error for all IDs in batch
        return [{"wikidata_id": qid, "error": str(e)} for qid in wiki_ids]


def load_all_individual_ids() -> list:
    """Load all individual IDs from the JSON batches."""
    json_batches_dir = os.path.join(
        os.path.dirname(__file__), "..", "..", "data", "extracted", "individuals_qlever", "json_batches"
    )

    all_ids = []
    batch_files = sorted([f for f in os.listdir(json_batches_dir) if f.startswith("batch_") and f.endswith(".json")])

    print(f"Loading IDs from {len(batch_files)} batch files...")
    for batch_file in tqdm(batch_files, desc="Loading batches"):
        with open(os.path.join(json_batches_dir, batch_file), "r") as f:
            data = json.load(f)
            for item in data:
                all_ids.append(item["wikidata_id"])

    return all_ids


def main():
    set_endpoint(QLEVER_ENDPOINT)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(JSON_DIR, exist_ok=True)

    # Resume support
    processed_ids = get_processed_ids()
    existing_batches = len([f for f in os.listdir(JSON_DIR) if f.startswith("batch_") and f.endswith(".json")]) if os.path.exists(JSON_DIR) else 0
    batch_num = existing_batches

    if not processed_ids:
        with open(PROGRESS_FILE, "w") as f:
            f.write("=" * 60 + "\n")
            f.write("DATE PRECISION EXTRACTION (QLever)\n")
            f.write("=" * 60 + "\n\n")

    log_progress(f"Endpoint: {QLEVER_ENDPOINT}")
    log_progress("Loading individual IDs...")

    all_ids = load_all_individual_ids()

    if TEST_LIMIT:
        all_ids = all_ids[:TEST_LIMIT]
        log_progress(f"TEST MODE: Limited to {TEST_LIMIT:,} individuals")

    total = len(all_ids)
    log_progress(f"Total individuals: {total:,}")

    if processed_ids:
        log_progress(f"Resuming: {len(processed_ids):,} already processed ({batch_num} batches)")

    # Filter already processed
    remaining_ids = [id for id in all_ids if id not in processed_ids]
    log_progress(f"Remaining: {len(remaining_ids):,}")

    if not remaining_ids:
        log_progress("All individuals already processed!")
        return

    # Split into query batches
    query_batches = [remaining_ids[i:i+QUERY_BATCH_SIZE] for i in range(0, len(remaining_ids), QUERY_BATCH_SIZE)]
    log_progress(f"Query batches: {len(query_batches):,} (size={QUERY_BATCH_SIZE})")

    all_results = []
    all_failures = []

    start_time = time.time()
    processed_count = len(processed_ids)
    initial_count = processed_count

    log_progress(f"Starting with {NUM_THREADS} threads...")
    log_progress(f"Checkpoint every {CHECKPOINT_EVERY:,} individuals")

    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        future_to_batch = {executor.submit(get_date_precision_batch, batch): batch for batch in query_batches}

        pbar = tqdm(total=len(remaining_ids), desc="Extracting precision", initial=0)

        for future in as_completed(future_to_batch):
            batch_ids = future_to_batch[future]
            try:
                results = future.result()
                for result in results:
                    if "error" not in result:
                        all_results.append(result)
                    else:
                        all_failures.append(result)
                    processed_ids.add(result["wikidata_id"])
                    processed_count += 1

                pbar.update(len(batch_ids))

            except Exception as e:
                for qid in batch_ids:
                    all_failures.append({"wikidata_id": qid, "error": str(e)})
                    processed_ids.add(qid)
                    processed_count += 1
                pbar.update(len(batch_ids))

            # Progress logging every 5000
            if processed_count % 5000 < QUERY_BATCH_SIZE:
                elapsed = time.time() - start_time
                rate = (processed_count - initial_count) / elapsed if elapsed > 0 else 0
                remaining = total - processed_count
                eta_hours = (remaining / rate / 3600) if rate > 0 else 0
                log_progress(
                    f"Progress: {processed_count:,}/{total:,} ({100*processed_count/total:.1f}%) | "
                    f"Rate: {rate:.1f}/s | ETA: {eta_hours:.1f}h | "
                    f"OK: {len(all_results):,} | Fail: {len(all_failures):,}"
                )

            # Checkpoint
            if len(all_results) >= CHECKPOINT_EVERY:
                batch_num += 1
                save_batch_to_json(all_results, batch_num)
                save_processed_ids(processed_ids)
                log_progress(f">>> SAVED batch_{batch_num:04d}.json ({len(all_results):,} records)")
                all_results = []

        pbar.close()

    # Final save
    if all_results:
        batch_num += 1
        save_batch_to_json(all_results, batch_num)
        save_processed_ids(processed_ids)
        log_progress(f">>> FINAL: batch_{batch_num:04d}.json ({len(all_results):,} records)")

    # Save failures
    if all_failures:
        failures_file = os.path.join(OUTPUT_DIR, "failures.json")
        with open(failures_file, "w") as f:
            json.dump(all_failures, f)
        log_progress(f"Failures saved to: {failures_file}")

    # Report
    elapsed = time.time() - start_time
    log_progress("\n" + "=" * 60)
    log_progress("EXTRACTION COMPLETE")
    log_progress("=" * 60)
    log_progress(f"Total processed: {processed_count:,}")
    log_progress(f"Successful: {processed_count - len(all_failures):,}")
    log_progress(f"Failures: {len(all_failures):,}")
    log_progress(f"Time: {elapsed/3600:.2f} hours")
    if elapsed > 0:
        log_progress(f"Rate: {(processed_count - initial_count)/elapsed:.1f}/s")
    log_progress(f"Batches: {batch_num}")
    log_progress(f"Output: {JSON_DIR}")


if __name__ == "__main__":
    main()
