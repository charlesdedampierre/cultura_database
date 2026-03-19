"""Speed test for individual extraction to find optimal parameters.

Tests:
1. Single query vs paginated queries
2. Different numbers of parallel workers (1, 2, 4, 8, 16)
3. Different page sizes (10000, 50000, 100000)

Saves results to speed_test_results.json
"""

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

# Test occupations of different sizes
TEST_OCCUPATIONS = [
    {"id": "Q3055126", "name": "entomologist", "expected_size": "medium"},  # ~20k
    {"id": "Q1234713", "name": "theologian", "expected_size": "large"},  # ~40k
    {"id": "Q36180", "name": "writer", "expected_size": "very_large"},  # ~1M+
]


def count_individuals(occ_id: str) -> int:
    """Count individuals for an occupation."""
    query = f"""
    SELECT (COUNT(?item) AS ?count)
    WHERE {{
      ?item wdt:P106 wd:{occ_id} .
    }}
    """
    try:
        rows = sparql_query(query)
        if rows:
            return int(rows[0]["count"])
    except Exception as e:
        print(f"  Error counting: {e}")
    return -1


def test_single_query(occ_id: str) -> dict:
    """Test fetching all at once (no pagination)."""
    query = f"""
    SELECT ?item ?itemLabel
    WHERE {{
      ?item wdt:P106 wd:{occ_id} .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language 'en'. }}
    }}
    """
    start = time.time()
    try:
        rows = sparql_query(query)
        elapsed = time.time() - start
        return {"method": "single", "count": len(rows), "time": elapsed, "error": None}
    except Exception as e:
        elapsed = time.time() - start
        return {"method": "single", "count": 0, "time": elapsed, "error": str(e)}


def test_paginated(occ_id: str, page_size: int) -> dict:
    """Test fetching with pagination."""
    all_results = []
    offset = 0
    start = time.time()
    errors = []

    while True:
        query = f"""
        SELECT ?item ?itemLabel
        WHERE {{
          ?item wdt:P106 wd:{occ_id} .
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language 'en'. }}
        }}
        LIMIT {page_size}
        OFFSET {offset}
        """
        try:
            rows = sparql_query(query)
            if not rows:
                break
            all_results.extend(rows)
            if len(rows) < page_size:
                break
            offset += page_size
        except Exception as e:
            errors.append(f"Offset {offset}: {e}")
            break

    elapsed = time.time() - start
    return {
        "method": f"paginated_{page_size}",
        "count": len(all_results),
        "time": elapsed,
        "error": errors if errors else None,
    }


def fetch_occupation(occ_id: str, page_size: int = 50000) -> list:
    """Fetch individuals for one occupation (for parallel testing)."""
    all_results = []
    offset = 0

    while True:
        query = f"""
        SELECT ?item
        WHERE {{
          ?item wdt:P106 wd:{occ_id} .
        }}
        LIMIT {page_size}
        OFFSET {offset}
        """
        try:
            rows = sparql_query(query)
            if not rows:
                break
            all_results.extend(rows)
            if len(rows) < page_size:
                break
            offset += page_size
        except:
            break

    return all_results


def test_parallel_workers(occ_ids: list, num_workers: int) -> dict:
    """Test parallel fetching with N workers."""
    start = time.time()
    total_count = 0

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = {executor.submit(fetch_occupation, oid): oid for oid in occ_ids}
        for future in as_completed(futures):
            results = future.result()
            total_count += len(results)

    elapsed = time.time() - start
    return {
        "workers": num_workers,
        "total_count": total_count,
        "time": elapsed,
        "occupations": len(occ_ids),
    }


def main():
    print("=" * 60)
    print("SPEED TEST FOR INDIVIDUAL EXTRACTION")
    print("=" * 60)

    results = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tests": {},
    }

    # First, get counts for test occupations
    print("\n1. Counting individuals in test occupations...")
    for occ in TEST_OCCUPATIONS:
        count = count_individuals(occ["id"])
        occ["actual_count"] = count
        print(f"   {occ['name']} ({occ['id']}): {count:,} individuals")

    results["test_occupations"] = TEST_OCCUPATIONS

    # Test single vs paginated on medium occupation
    print("\n2. Testing single query vs pagination (entomologist ~20k)...")
    medium_occ = TEST_OCCUPATIONS[0]

    print("   Testing single query...")
    single_result = test_single_query(medium_occ["id"])
    print(f"   Single: {single_result['count']:,} in {single_result['time']:.1f}s - Error: {single_result['error']}")

    page_sizes = [10000, 50000]
    paginated_results = []
    for ps in page_sizes:
        print(f"   Testing page size {ps}...")
        res = test_paginated(medium_occ["id"], ps)
        paginated_results.append(res)
        print(f"   Page {ps}: {res['count']:,} in {res['time']:.1f}s - Error: {res['error']}")

    results["tests"]["query_methods"] = {
        "occupation": medium_occ["name"],
        "single": single_result,
        "paginated": paginated_results,
    }

    # Test parallel workers on small occupations
    print("\n3. Testing parallel workers...")

    # Get some small occupations for parallel test
    occupations_path = os.path.join(OUTPUT_DIR, "occupations.json")
    with open(occupations_path) as f:
        all_occupations = json.load(f)

    # Pick 20 random small occupations for parallel test
    test_occ_ids = [o["occupation_wikidata_id"] for o in all_occupations[:20]]

    worker_counts = [1, 2, 4, 8, 12, 16]
    parallel_results = []

    for num_workers in worker_counts:
        print(f"   Testing {num_workers} workers on 20 occupations...")
        res = test_parallel_workers(test_occ_ids, num_workers)
        parallel_results.append(res)
        print(f"   {num_workers} workers: {res['time']:.1f}s total")

    results["tests"]["parallel_workers"] = parallel_results

    # Find optimal configuration
    best_parallel = min(parallel_results, key=lambda x: x["time"])
    best_page = min(paginated_results, key=lambda x: x["time"]) if all(r["error"] is None for r in paginated_results) else paginated_results[0]

    results["optimal"] = {
        "workers": best_parallel["workers"],
        "page_size": int(best_page["method"].split("_")[1]) if "_" in best_page["method"] else 50000,
        "use_pagination": single_result["error"] is not None,
    }

    # Save results
    output_path = os.path.join(OUTPUT_DIR, "speed_test_results.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    print(f"\nSingle query works: {single_result['error'] is None}")
    print(f"Best page size: {results['optimal']['page_size']}")
    print(f"Best worker count: {results['optimal']['workers']}")
    print(f"\nRecommendation:")
    print(f"  - Use pagination: {results['optimal']['use_pagination']}")
    print(f"  - Page size: {results['optimal']['page_size']}")
    print(f"  - Workers: {results['optimal']['workers']}")
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
