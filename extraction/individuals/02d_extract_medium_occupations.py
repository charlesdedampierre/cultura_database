"""Extract medium-sized occupations using cursor-based pagination.

Targets: actor, university teacher, economist, historian, theologian
(Excludes writer and researcher which are too large)
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
PROGRESS_FILE = os.path.join(OUTPUT_DIR, "medium_occ_progress.json")

# Settings
PAGE_SIZE = 50_000
DELAY_BETWEEN_PAGES = 2
ENDPOINT = "https://query.wikidata.org/sparql"
HEADERS = {"Accept": "application/json", "User-Agent": "CulturaDatabase/1.0"}

# Occupations to extract (excluding writer Q36180 and researcher Q1650915)
OCCUPATIONS = [
    ("Q33999", "actor", 365_014),
    ("Q1622272", "university teacher", 316_059),
    ("Q188094", "economist", 56_666),
    ("Q201788", "historian", 120_733),
    ("Q1234713", "theologian", 43_556),
]


def log(msg):
    print(msg, flush=True)


def clean_json(s):
    """Remove control characters that break JSON parsing."""
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', s)


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}


def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f)


def sparql_query(query: str, timeout: int = 300) -> list[dict] | None:
    """Execute SPARQL query with retries."""
    for attempt in range(5):
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
            wait = 60 * (attempt + 1)
            log(f"      Timeout (attempt {attempt+1}/5), retry in {wait}s...")
            time.sleep(wait)
        except requests.exceptions.HTTPError as e:
            if "504" in str(e) or "502" in str(e):
                wait = 60 * (attempt + 1)
                log(f"      Gateway error (attempt {attempt+1}/5), retry in {wait}s...")
                time.sleep(wait)
            else:
                raise
        except json.JSONDecodeError as e:
            wait = 30 * (attempt + 1)
            log(f"      JSON error (attempt {attempt+1}/5): {str(e)[:40]}, retry in {wait}s...")
            time.sleep(wait)
        except Exception as e:
            wait = 30 * (attempt + 1)
            log(f"      Error (attempt {attempt+1}/5): {str(e)[:50]}, retry in {wait}s...")
            time.sleep(wait)
    return None


def is_complete(occ_id: str) -> bool:
    filepath = os.path.join(OCCUPATION_DIR, f"{occ_id}.json")
    if not os.path.exists(filepath):
        return False
    try:
        with open(filepath) as f:
            data = json.load(f)
        return data.get("error") is None and not data.get("partial") and data.get("count", 0) > 0
    except:
        return False


def get_existing_data(occ_id: str) -> tuple[list, str]:
    """Get existing partial results and last cursor."""
    filepath = os.path.join(OCCUPATION_DIR, f"{occ_id}.json")
    if os.path.exists(filepath):
        try:
            with open(filepath) as f:
                data = json.load(f)
            if data.get("results"):
                return data["results"], data.get("last_cursor", "")
        except:
            pass
    return [], ""


def save_result(occ_id, occ_name, results, error=None, partial=False, last_cursor=""):
    filepath = os.path.join(OCCUPATION_DIR, f"{occ_id}.json")
    data = {
        "occupation_id": occ_id,
        "occupation_name": occ_name,
        "count": len(results),
        "results": results,
        "error": error,
    }
    if partial:
        data["partial"] = True
        data["last_cursor"] = last_cursor
    with open(filepath, "w") as f:
        json.dump(data, f)


def fetch_occupation(occ_id: str, occ_name: str, expected: int):
    """Fetch all individuals using cursor-based pagination."""

    # Check if already complete
    if is_complete(occ_id):
        log(f"  Already complete, skipping")
        return True

    # Load existing partial data
    all_results, last_cursor = get_existing_data(occ_id)

    if all_results:
        log(f"  Resuming from {len(all_results):,} (cursor: {last_cursor[-20:] if last_cursor else 'start'})")

    # Progress bar for this occupation
    pbar = tqdm(total=expected, initial=len(all_results), desc=f"  {occ_name}", unit=" items")

    page = 1
    consecutive_failures = 0

    while True:
        # Build cursor filter
        if last_cursor:
            filter_clause = f"FILTER(?item > <{last_cursor}>)"
        else:
            filter_clause = ""

        query = f"""
        SELECT ?item ?itemLabel WHERE {{
          ?item wdt:P106 wd:{occ_id} .
          {filter_clause}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
        }}
        ORDER BY ?item
        LIMIT {PAGE_SIZE}
        """

        results = sparql_query(query)

        if results is None:
            consecutive_failures += 1
            if consecutive_failures >= 3:
                log(f"  Too many failures, saving partial progress")
                save_result(occ_id, occ_name, all_results, partial=True, last_cursor=last_cursor)
                pbar.close()
                return False
            continue

        consecutive_failures = 0

        if not results:
            # No more results
            pbar.close()
            log(f"  Complete! Total: {len(all_results):,}")
            save_result(occ_id, occ_name, all_results)
            return True

        # Extract data
        for r in results:
            item_url = r.get("item", {}).get("value", "")
            wikidata_id = item_url.split("/")[-1] if item_url else ""
            if wikidata_id:
                all_results.append({
                    "wikidata_id": wikidata_id,
                    "name": r.get("itemLabel", {}).get("value", ""),
                })

        # Update cursor
        last_cursor = results[-1]["item"]["value"]

        pbar.update(len(results))

        # Save progress periodically
        save_result(occ_id, occ_name, all_results, partial=True, last_cursor=last_cursor)

        if len(results) < PAGE_SIZE:
            # Last page
            pbar.close()
            log(f"  Complete! Total: {len(all_results):,}")
            save_result(occ_id, occ_name, all_results)
            return True

        page += 1
        time.sleep(DELAY_BETWEEN_PAGES)

    pbar.close()
    return False


def main():
    log("=" * 60)
    log("Extracting medium-sized occupations (50k batches)")
    log("=" * 60)

    total_expected = sum(exp for _, _, exp in OCCUPATIONS)
    log(f"Total expected: ~{total_expected:,} entities\n")

    results_summary = []
    start_time = datetime.now()

    for occ_id, occ_name, expected in OCCUPATIONS:
        log(f"\n[{occ_name}] ({occ_id}) - expected ~{expected:,}")

        success = fetch_occupation(occ_id, occ_name, expected)

        # Get actual count
        filepath = os.path.join(OCCUPATION_DIR, f"{occ_id}.json")
        actual = 0
        if os.path.exists(filepath):
            with open(filepath) as f:
                data = json.load(f)
                actual = data.get("count", 0)

        results_summary.append({
            "occupation": occ_name,
            "expected": expected,
            "actual": actual,
            "success": success
        })

    duration = (datetime.now() - start_time).total_seconds()

    log("\n" + "=" * 60)
    log("SUMMARY")
    log("=" * 60)

    total_actual = 0
    for r in results_summary:
        status = "OK" if r["success"] else "PARTIAL"
        log(f"  {r['occupation']:20} {r['actual']:>10,} / {r['expected']:>10,}  [{status}]")
        total_actual += r["actual"]

    log("-" * 60)
    log(f"  {'TOTAL':20} {total_actual:>10,} / {total_expected:>10,}")
    log(f"\nDuration: {duration/60:.1f} minutes")


if __name__ == "__main__":
    main()
