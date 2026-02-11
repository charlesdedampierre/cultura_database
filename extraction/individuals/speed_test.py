"""Speed test for Wikidata extraction - find optimal batch size and workers."""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from wikidata_api import sparql_query

OUTPUT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "extracted", "individuals"
)


def test_single_query(occupation_id: str) -> tuple[int, float]:
    """Test single occupation query."""
    query = f"""
    SELECT ?item ?itemLabel
    WHERE {{
      ?item wdt:P106 wd:{occupation_id} .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language 'en'. }}
    }}
    """
    start = time.time()
    rows = sparql_query(query)
    elapsed = time.time() - start
    return len(rows), elapsed


def test_batch_query(occupation_ids: list[str]) -> tuple[int, float]:
    """Test batched query with VALUES clause."""
    values = " ".join(f"wd:{oid}" for oid in occupation_ids)
    query = f"""
    SELECT ?item ?itemLabel ?occupation
    WHERE {{
      VALUES ?occupation {{ {values} }}
      ?item wdt:P106 ?occupation .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language 'en'. }}
    }}
    """
    start = time.time()
    rows = sparql_query(query)
    elapsed = time.time() - start
    return len(rows), elapsed


def test_parallel_single(occupation_ids: list[str], num_workers: int) -> tuple[int, float]:
    """Test parallel single queries."""
    start = time.time()
    total_results = 0

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(test_single_query, oid) for oid in occupation_ids]
        for future in as_completed(futures):
            count, _ = future.result()
            total_results += count

    elapsed = time.time() - start
    return total_results, elapsed


def main():
    # Load occupations
    occupations_path = os.path.join(OUTPUT_DIR, "occupations.json")
    with open(occupations_path) as f:
        occupations = json.load(f)

    # Skip first 100 (large categories) and take sample of 30 medium-sized occupations
    sample_ids = [o["occupation_wikidata_id"] for o in occupations[100:130]]

    print("=" * 60)
    print("WIKIDATA SPEED TEST")
    print("=" * 60)
    print(f"Testing with {len(sample_ids)} sample occupations\n")

    results = []

    # Test 1: Single sequential queries
    print("Test 1: Sequential single queries (baseline)...")
    start = time.time()
    total = 0
    for oid in sample_ids[:5]:
        count, _ = test_single_query(oid)
        total += count
    elapsed = time.time() - start
    rate = 5 / elapsed
    print(f"  5 queries in {elapsed:.1f}s = {rate:.2f} queries/sec | {total} results")
    results.append(("Sequential (1 worker)", rate, total))

    # Test 2: Parallel single queries with different worker counts
    for workers in [2, 3, 4, 6, 8]:
        print(f"\nTest 2.{workers}: Parallel single queries ({workers} workers)...")
        try:
            total, elapsed = test_parallel_single(sample_ids[:10], workers)
            rate = 10 / elapsed
            print(f"  10 queries in {elapsed:.1f}s = {rate:.2f} queries/sec | {total} results")
            results.append((f"Parallel ({workers} workers)", rate, total))
        except Exception as e:
            print(f"  FAILED: {e}")
            results.append((f"Parallel ({workers} workers)", 0, 0))
        time.sleep(2)  # Cooldown between tests

    # Test 3: Batched queries with different batch sizes
    for batch_size in [5, 10, 20, 50]:
        print(f"\nTest 3.{batch_size}: Batched query (batch_size={batch_size})...")
        try:
            batch = sample_ids[:batch_size]
            total, elapsed = test_batch_query(batch)
            rate = batch_size / elapsed
            print(f"  {batch_size} occupations in {elapsed:.1f}s = {rate:.2f} occupations/sec | {total} results")
            results.append((f"Batched (size={batch_size})", rate, total))
        except Exception as e:
            print(f"  FAILED: {e}")
            results.append((f"Batched (size={batch_size})", 0, 0))
        time.sleep(2)

    # Test 4: Parallel batched queries
    print(f"\nTest 4: Parallel batched queries (batch=10, workers=3)...")
    try:
        batches = [sample_ids[i:i+10] for i in range(0, 30, 10)]
        start = time.time()
        total = 0
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(test_batch_query, batch) for batch in batches]
            for future in as_completed(futures):
                count, _ = future.result()
                total += count
        elapsed = time.time() - start
        rate = 30 / elapsed
        print(f"  30 occupations in {elapsed:.1f}s = {rate:.2f} occupations/sec | {total} results")
        results.append(("Parallel batched (10x3)", rate, total))
    except Exception as e:
        print(f"  FAILED: {e}")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY (sorted by speed)")
    print("=" * 60)
    results.sort(key=lambda x: x[1], reverse=True)
    for name, rate, total in results:
        if rate > 0:
            print(f"  {name:30s} : {rate:.2f} queries/sec")

    # Estimate total time for 4828 occupations
    print("\n" + "=" * 60)
    print("ESTIMATED TIME FOR 4828 OCCUPATIONS")
    print("=" * 60)
    for name, rate, _ in results[:5]:
        if rate > 0:
            est_time = 4828 / rate
            hours = int(est_time // 3600)
            minutes = int((est_time % 3600) // 60)
            print(f"  {name:30s} : {hours}h {minutes}m")


if __name__ == "__main__":
    main()
