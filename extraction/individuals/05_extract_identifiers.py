"""
Extract external identifiers for individuals from Wikidata.

Following extraction_rules.md:
- Speed test with different thread/batch configurations
- Save as JSON first (database integration later)
- Progress tracking with tqdm and txt file
- Checkpointing for resume
- Failure report for reruns

Usage:
  python 05_extract_identifiers.py --speed-test      # Test optimal configuration
  python 05_extract_identifiers.py --test 1000       # Test on 1000 individuals
  python 05_extract_identifiers.py --full            # Full extraction (use with nohup)

For full extraction:
  caffeinate -i nohup python 05_extract_identifiers.py --full &
"""

import json
import os
import random
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from threading import Lock
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from wikidata_api import sparql_query

# Paths
BASE_DIR = Path(__file__).parent.parent.parent
OUTPUT_DIR = BASE_DIR / "data" / "extracted" / "individuals_qlever" / "identifiers"
JSON_DIR = OUTPUT_DIR / "json_batches"

PROGRESS_FILE = OUTPUT_DIR / "extraction_progress_identifiers.txt"
PROCESSED_IDS_FILE = OUTPUT_DIR / "processed_ids_identifiers.json"
FAILURES_FILE = OUTPUT_DIR / "extraction_failures_identifiers.json"
REPORT_FILE = OUTPUT_DIR / "extraction_report_identifiers.json"

# Thread-safe lock
progress_lock = Lock()


def ensure_dirs():
    """Create output directories."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_DIR.mkdir(parents=True, exist_ok=True)


def log_progress(message: str):
    """Log progress to file and console."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}"
    print(log_line)
    with progress_lock:
        with open(PROGRESS_FILE, "a") as f:
            f.write(log_line + "\n")


def get_identifiers(wiki_id: str) -> dict:
    """Get all external identifiers for an individual from Wikidata."""
    query = """
    SELECT ?prop ?propLabel ?value WHERE {
      wd:%s ?p ?value .
      ?prop wikibase:directClaim ?p .
      ?prop wikibase:propertyType wikibase:ExternalId .
      SERVICE wikibase:label { bd:serviceParam wikibase:language 'en'. }
    }
    """ % wiki_id

    try:
        rows = sparql_query(query)
        identifiers = []
        for row in rows:
            prop_uri = row.get("prop", "")
            prop_id = prop_uri.split("/")[-1] if "/" in prop_uri else prop_uri
            prop_name = row.get("propLabel", "")
            value = row.get("value", "")
            identifiers.append({
                "property_id": prop_id,
                "property_name": prop_name,
                "value": value
            })
        return {"wikidata_id": wiki_id, "identifiers": identifiers, "count": len(identifiers)}
    except Exception as e:
        return {"wikidata_id": wiki_id, "error": str(e)}


def get_identifiers_batch(wiki_ids: list) -> list:
    """Get identifiers for multiple individuals in a single SPARQL query (much faster)."""
    if not wiki_ids:
        return []

    # Build VALUES clause
    values_str = " ".join([f"wd:{wid}" for wid in wiki_ids])

    query = f"""
    SELECT ?entity ?prop ?propLabel ?value WHERE {{
      VALUES ?entity {{ {values_str} }}
      ?entity ?p ?value .
      ?prop wikibase:directClaim ?p .
      ?prop wikibase:propertyType wikibase:ExternalId .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language 'en'. }}
    }}
    """

    try:
        rows = sparql_query(query)

        # Group results by entity
        results_by_entity = {wid: [] for wid in wiki_ids}

        for row in rows:
            entity_uri = row.get("entity", "")
            entity_id = entity_uri.split("/")[-1] if "/" in entity_uri else entity_uri

            if entity_id in results_by_entity:
                prop_uri = row.get("prop", "")
                prop_id = prop_uri.split("/")[-1] if "/" in prop_uri else prop_uri
                prop_name = row.get("propLabel", "")
                value = row.get("value", "")
                results_by_entity[entity_id].append({
                    "property_id": prop_id,
                    "property_name": prop_name,
                    "value": value
                })

        # Convert to list of results
        results = []
        for wid in wiki_ids:
            identifiers = results_by_entity.get(wid, [])
            results.append({
                "wikidata_id": wid,
                "identifiers": identifiers,
                "count": len(identifiers)
            })

        return results
    except Exception as e:
        # On error, return error for all IDs in batch
        return [{"wikidata_id": wid, "error": str(e)} for wid in wiki_ids]


def load_all_individual_ids() -> list:
    """Load all unique individual IDs from the database."""
    db_path = BASE_DIR / "cultura_database.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT wikidata_id FROM individuals")
    rows = [(row[0], None) for row in cursor.fetchall()]  # (wikidata_id, name=None)
    conn.close()
    return rows


def load_processed_ids() -> set:
    """Load set of already processed IDs."""
    if PROCESSED_IDS_FILE.exists():
        with open(PROCESSED_IDS_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_processed_ids(processed_ids: set):
    """Save processed IDs to file."""
    with open(PROCESSED_IDS_FILE, "w") as f:
        json.dump(list(processed_ids), f)


def save_json_batch(results: list, batch_num: int):
    """Save a batch of results as JSON."""
    batch_file = JSON_DIR / f"batch_{batch_num:04d}.json"
    with open(batch_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    return batch_file


def speed_test():
    """Test different thread/batch configurations to find optimal settings."""
    ensure_dirs()

    print("=" * 60)
    print("SPEED TEST - Finding optimal configuration")
    print("=" * 60)

    # Load sample of 200 individuals for testing
    all_individuals = load_all_individual_ids()
    random.seed(42)
    test_sample = random.sample(all_individuals, min(200, len(all_individuals)))
    test_ids = [wid for wid, _ in test_sample]

    configs = [
        (20, 100),  # 20 threads
        (30, 100),  # 30 threads
        (40, 100),  # 40 threads
        (50, 100),  # 50 threads
    ]

    results = []

    for num_threads, batch_size in configs:
        print(f"\nTesting: {num_threads} threads, batch size {batch_size}")

        start_time = time.time()
        processed = 0

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = {executor.submit(get_identifiers, wid): wid for wid in test_ids[:200]}

            for future in as_completed(futures):
                try:
                    result = future.result()
                    if "error" not in result:
                        processed += 1
                except:
                    pass

        elapsed = time.time() - start_time
        rate = processed / elapsed if elapsed > 0 else 0

        results.append({
            "threads": num_threads,
            "batch_size": batch_size,
            "processed": processed,
            "time": round(elapsed, 2),
            "rate": round(rate, 2)
        })

        print(f"  -> Processed {processed} in {elapsed:.1f}s = {rate:.1f}/s")

    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)

    best = max(results, key=lambda x: x["rate"])

    for r in results:
        marker = " <-- BEST" if r == best else ""
        print(f"  {r['threads']:2d} threads, batch {r['batch_size']:3d}: {r['rate']:.1f}/s{marker}")

    print(f"\nRecommended: {best['threads']} threads, batch size {best['batch_size']}")

    # Estimate full extraction time
    total_individuals = len(all_individuals)
    estimated_hours = total_individuals / best["rate"] / 3600
    print(f"\nEstimated time for {total_individuals:,} individuals: {estimated_hours:.1f} hours")

    return best


def run_extraction(individuals: list, num_threads: int = 10, query_batch_size: int = 50,
                   json_batch_size: int = 500, checkpoint_every: int = 10000, test_mode: bool = False):
    """Run the extraction process using batched SPARQL queries (much faster)."""
    ensure_dirs()

    # Load processed IDs for resume
    processed_ids = load_processed_ids()

    # Initialize progress file
    if not processed_ids:
        with open(PROGRESS_FILE, "w") as f:
            f.write("=" * 60 + "\n")
            f.write(f"IDENTIFIERS EXTRACTION {'(TEST)' if test_mode else '(FULL)'}\n")
            f.write(f"Started: {datetime.now().isoformat()}\n")
            f.write(f"Threads: {num_threads}, Query batch: {query_batch_size}, JSON batch: {json_batch_size}\n")
            f.write("=" * 60 + "\n\n")

    # Create lookup dict for names
    id_to_name = {wid: name for wid, name in individuals}
    all_ids = [wid for wid, _ in individuals]

    total = len(all_ids)
    log_progress(f"Total individuals: {total:,}")

    if processed_ids:
        log_progress(f"Resuming: {len(processed_ids):,} already processed")

    # Filter out already processed
    remaining_ids = [wid for wid in all_ids if wid not in processed_ids]
    log_progress(f"Remaining to process: {len(remaining_ids):,}")

    if not remaining_ids:
        log_progress("Nothing to process!")
        return

    # Split into query batches
    query_batches = [remaining_ids[i:i + query_batch_size] for i in range(0, len(remaining_ids), query_batch_size)]
    log_progress(f"Query batches: {len(query_batches):,} (each ~{query_batch_size} individuals)")

    # Track state
    all_failures = []
    json_results = []
    json_batch_num = len(list(JSON_DIR.glob("batch_*.json")))

    start_time = time.time()
    processed_count = len(processed_ids)
    initial_count = processed_count
    total_identifiers = 0

    log_progress(f"Starting extraction with {num_threads} threads, {query_batch_size} individuals per query...")

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = {executor.submit(get_identifiers_batch, batch): batch for batch in query_batches}

        pbar = tqdm(total=len(remaining_ids), desc="Extracting", unit="ind")

        for future in as_completed(futures):
            batch_ids = futures[future]

            try:
                results = future.result()

                for result in results:
                    wiki_id = result["wikidata_id"]
                    result["name"] = id_to_name.get(wiki_id)

                    if "error" not in result:
                        json_results.append(result)
                        total_identifiers += result.get("count", 0)
                    else:
                        all_failures.append({
                            "wikidata_id": wiki_id,
                            "name": id_to_name.get(wiki_id),
                            "error": result.get("error")
                        })

                    processed_ids.add(wiki_id)
                    processed_count += 1
                    pbar.update(1)

            except Exception as e:
                for wiki_id in batch_ids:
                    all_failures.append({
                        "wikidata_id": wiki_id,
                        "name": id_to_name.get(wiki_id),
                        "error": str(e)
                    })
                    processed_ids.add(wiki_id)
                    processed_count += 1
                    pbar.update(1)

            # Log progress every 100 individuals
            if processed_count % 100 == 0:
                elapsed = time.time() - start_time
                rate = (processed_count - initial_count) / elapsed if elapsed > 0 else 0
                remaining = total - processed_count
                eta_hours = (remaining / rate / 3600) if rate > 0 else 0
                with progress_lock:
                    with open(PROGRESS_FILE, "a") as f:
                        f.write(f"{processed_count:,}/{total:,} | {rate:.1f}/s | ETA: {eta_hours:.1f}h\n")

            # Save JSON batch
            if len(json_results) >= json_batch_size:
                json_batch_num += 1
                save_json_batch(json_results, json_batch_num)
                json_results = []

            # Checkpoint
            if processed_count % checkpoint_every == 0:
                save_processed_ids(processed_ids)

                with open(FAILURES_FILE, "w") as f:
                    json.dump(all_failures, f, indent=2)

                elapsed = time.time() - start_time
                rate = (processed_count - initial_count) / elapsed if elapsed > 0 else 0
                remaining = total - processed_count
                eta_hours = (remaining / rate / 3600) if rate > 0 else 0

                log_progress(
                    f"CHECKPOINT {processed_count:,}/{total:,} | "
                    f"Rate: {rate:.1f}/s | ETA: {eta_hours:.1f}h | "
                    f"Identifiers: {total_identifiers:,}"
                )

        pbar.close()

    # Final save
    if json_results:
        json_batch_num += 1
        save_json_batch(json_results, json_batch_num)

    save_processed_ids(processed_ids)

    with open(FAILURES_FILE, "w") as f:
        json.dump(all_failures, f, indent=2)

    # Generate report
    elapsed = time.time() - start_time
    rate = (processed_count - initial_count) / elapsed if elapsed > 0 else 0

    report = {
        "extraction_type": "identifiers",
        "started": datetime.now().isoformat(),
        "test_mode": test_mode,
        "config": {
            "threads": num_threads,
            "query_batch_size": query_batch_size,
            "json_batch_size": json_batch_size,
            "checkpoint_every": checkpoint_every
        },
        "results": {
            "total_individuals": total,
            "processed": processed_count,
            "successful": processed_count - len(all_failures),
            "failures": len(all_failures),
            "total_identifiers": total_identifiers,
            "json_batches": json_batch_num
        },
        "performance": {
            "elapsed_seconds": round(elapsed, 1),
            "elapsed_minutes": round(elapsed / 60, 1),
            "rate_per_second": round(rate, 2)
        },
        "output": {
            "json_dir": str(JSON_DIR),
            "failures_file": str(FAILURES_FILE),
            "progress_file": str(PROGRESS_FILE)
        }
    }

    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=2)

    # Final log
    log_progress("\n" + "=" * 60)
    log_progress("EXTRACTION COMPLETE")
    log_progress("=" * 60)
    log_progress(f"Total processed: {processed_count:,}")
    log_progress(f"Successful: {processed_count - len(all_failures):,}")
    log_progress(f"Failures: {len(all_failures):,}")
    log_progress(f"Total identifiers extracted: {total_identifiers:,}")
    log_progress(f"JSON batches saved: {json_batch_num}")
    log_progress(f"Time: {elapsed/60:.1f} min ({rate:.1f}/s)")
    log_progress(f"Report: {REPORT_FILE}")

    return report


def test_sample(sample_size: int = 1000):
    """Test extraction on a sample."""
    ensure_dirs()

    log_progress(f"=== TEST MODE: {sample_size} individuals ===")

    all_individuals = load_all_individual_ids()
    log_progress(f"Total in database: {len(all_individuals):,}")

    random.seed(42)
    sample = random.sample(all_individuals, min(sample_size, len(all_individuals)))

    # Clear previous test data
    for f in [PROCESSED_IDS_FILE, FAILURES_FILE]:
        if f.exists():
            f.unlink()
    for f in JSON_DIR.glob("batch_*.json"):
        f.unlink()

    return run_extraction(sample, num_threads=15, query_batch_size=50,
                         json_batch_size=500, checkpoint_every=1000, test_mode=True)


def run_full():
    """Run full extraction."""
    ensure_dirs()

    log_progress("=== FULL EXTRACTION ===")

    all_individuals = load_all_individual_ids()

    # 8 threads, 50 individuals per SPARQL query - balanced for speed and rate limits
    return run_extraction(all_individuals, num_threads=8, query_batch_size=50,
                         json_batch_size=500, checkpoint_every=10000, test_mode=False)


def retry_failures():
    """Retry failed extractions with lower tempo."""
    ensure_dirs()

    if not FAILURES_FILE.exists():
        print("No failures file found. Run full extraction first.")
        return

    with open(FAILURES_FILE, "r") as f:
        failures = json.load(f)

    if not failures:
        print("No failures to retry!")
        return

    log_progress(f"=== RETRY MODE: {len(failures)} failures ===")
    log_progress("Using 5 threads with slower tempo...")

    # Convert failures to (wikidata_id, name) format
    individuals = [(f["wikidata_id"], f.get("name")) for f in failures]

    # Remove these from processed_ids so they get reprocessed
    processed_ids = load_processed_ids()
    for wid, _ in individuals:
        processed_ids.discard(wid)
    save_processed_ids(processed_ids)

    # Clear failures file
    with open(FAILURES_FILE, "w") as f:
        json.dump([], f)

    return run_extraction(individuals, num_threads=5, query_batch_size=20,
                         json_batch_size=200, checkpoint_every=1000, test_mode=False)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract identifiers from Wikidata")
    parser.add_argument("--speed-test", action="store_true", help="Run speed test")
    parser.add_argument("--test", type=int, help="Test on N individuals")
    parser.add_argument("--full", action="store_true", help="Full extraction")
    parser.add_argument("--retry", action="store_true", help="Retry failures with lower tempo")

    args = parser.parse_args()

    if args.speed_test:
        speed_test()
    elif args.test:
        result = test_sample(args.test)
        print("\n" + json.dumps(result, indent=2))
    elif args.full:
        run_full()
    elif args.retry:
        retry_failures()
    else:
        print(__doc__)
        print("\nUsage:")
        print("  python 05_extract_identifiers.py --full    # Full extraction (20 threads)")
        print("  python 05_extract_identifiers.py --retry   # Retry failures (5 threads)")
        print("\nFor full extraction with nohup:")
        print("  caffeinate -i nohup python 05_extract_identifiers.py --full &")
        print("  tail -f data/extracted/individuals_qlever/identifiers/extraction_progress_identifiers.txt")
