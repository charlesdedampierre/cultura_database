"""Speed test to find optimal multiprocessing and batch settings for full extraction."""

import json
import os
import sys
import time
from multiprocessing import Pool
from concurrent.futures import ThreadPoolExecutor
import statistics

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from wikidata_api import sparql_query

# Test sample - use 50 random IDs
TEST_IDS = [
    "Q42", "Q5582", "Q7243", "Q9439", "Q5879", "Q1339", "Q5673", "Q6882",
    "Q8023", "Q9327", "Q7186", "Q8877", "Q3033", "Q5593", "Q7374", "Q2831",
    "Q1744", "Q5749", "Q8573", "Q6294", "Q4518", "Q8446", "Q9235", "Q7836",
    "Q1435", "Q3454", "Q8612", "Q2973", "Q6589", "Q1637", "Q5432", "Q9871",
    "Q4523", "Q7612", "Q3845", "Q8234", "Q2156", "Q6734", "Q1928", "Q5643",
    "Q9012", "Q4367", "Q7890", "Q3214", "Q8567", "Q2345", "Q6789", "Q1234",
    "Q5678", "Q9999"
]


def get_basic_info(wiki_id: str) -> dict | None:
    """Get biographical info for a single individual (simplified for speed test)."""
    query = """
    SELECT ?label ?genderLabel ?birthdateLabel ?deathdateLabel
           ?nationality ?nationalityLabel
           ?birthcity ?birthcityLabel
           ?occupation ?occupationLabel
    WHERE {
      OPTIONAL { wd:%s rdfs:label ?label. FILTER(LANG(?label) = 'en') }
      OPTIONAL { wd:%s wdt:P21 ?gender. }
      OPTIONAL { wd:%s wdt:P569 ?birthdate. }
      OPTIONAL { wd:%s wdt:P570 ?deathdate. }
      OPTIONAL { wd:%s wdt:P27 ?nationality. }
      OPTIONAL { wd:%s wdt:P19 ?birthcity. }
      OPTIONAL { wd:%s wdt:P106 ?occupation. }
      SERVICE wikibase:label { bd:serviceParam wikibase:language 'en'. }
    }
    """ % tuple([wiki_id] * 7)

    try:
        rows = sparql_query(query)
        return {"wikidata_id": wiki_id, "success": True, "rows": len(rows)}
    except Exception as e:
        return {"wikidata_id": wiki_id, "success": False, "error": str(e)}


def test_multiprocessing(num_workers: int, test_ids: list) -> dict:
    """Test with specific number of workers."""
    start = time.time()

    with Pool(num_workers) as p:
        results = list(p.map(get_basic_info, test_ids))

    elapsed = time.time() - start
    successful = sum(1 for r in results if r and r.get("success"))

    return {
        "workers": num_workers,
        "total": len(test_ids),
        "successful": successful,
        "elapsed": round(elapsed, 2),
        "rate": round(len(test_ids) / elapsed, 2)
    }


def test_threading(num_threads: int, test_ids: list) -> dict:
    """Test with ThreadPoolExecutor."""
    start = time.time()

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        results = list(executor.map(get_basic_info, test_ids))

    elapsed = time.time() - start
    successful = sum(1 for r in results if r and r.get("success"))

    return {
        "threads": num_threads,
        "total": len(test_ids),
        "successful": successful,
        "elapsed": round(elapsed, 2),
        "rate": round(len(test_ids) / elapsed, 2)
    }


def main():
    print("="*60)
    print("SPEED TEST FOR FULL EXTRACTION")
    print("="*60)
    print(f"Testing with {len(TEST_IDS)} IDs\n")

    # Test different worker counts
    worker_counts = [2, 4, 6, 8, 10, 12]

    print("Testing MULTIPROCESSING (Pool):")
    print("-" * 40)
    mp_results = []
    for workers in worker_counts:
        print(f"  Testing {workers} workers...", end=" ", flush=True)
        result = test_multiprocessing(workers, TEST_IDS)
        print(f"{result['rate']} req/s (success: {result['successful']}/{result['total']})")
        mp_results.append(result)
        time.sleep(2)  # Avoid rate limiting

    print("\nTesting THREADING (ThreadPoolExecutor):")
    print("-" * 40)
    thread_results = []
    for threads in worker_counts:
        print(f"  Testing {threads} threads...", end=" ", flush=True)
        result = test_threading(threads, TEST_IDS)
        print(f"{result['rate']} req/s (success: {result['successful']}/{result['total']})")
        thread_results.append(result)
        time.sleep(2)

    # Find optimal
    best_mp = max(mp_results, key=lambda x: x['rate'])
    best_thread = max(thread_results, key=lambda x: x['rate'])

    print("\n" + "="*60)
    print("RESULTS")
    print("="*60)
    print(f"Best multiprocessing: {best_mp['workers']} workers @ {best_mp['rate']} req/s")
    print(f"Best threading: {best_thread['threads']} threads @ {best_thread['rate']} req/s")

    if best_mp['rate'] >= best_thread['rate']:
        print(f"\n>>> RECOMMENDATION: Use multiprocessing with {best_mp['workers']} workers")
        optimal = {"method": "multiprocessing", "workers": best_mp['workers'], "rate": best_mp['rate']}
    else:
        print(f"\n>>> RECOMMENDATION: Use threading with {best_thread['threads']} threads")
        optimal = {"method": "threading", "workers": best_thread['threads'], "rate": best_thread['rate']}

    # Estimate time for full extraction
    total_individuals = 2810360
    estimated_hours = total_individuals / optimal['rate'] / 3600
    print(f"\nEstimated time for {total_individuals:,} individuals: {estimated_hours:.1f} hours")

    # Save results
    results = {
        "test_size": len(TEST_IDS),
        "multiprocessing_results": mp_results,
        "threading_results": thread_results,
        "optimal": optimal,
        "estimated_hours": round(estimated_hours, 1)
    }

    output_path = os.path.join(os.path.dirname(__file__), "speed_test_results.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
