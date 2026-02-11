"""Re-extract failed occupations using cursor-based pagination.

Uses FILTER(?item > last_item) instead of OFFSET for much faster queries.
"""

import json
import os
import re
import time
import requests
from datetime import datetime

# Paths
BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "extracted", "individuals")
OCCUPATION_DIR = os.path.join(OUTPUT_DIR, "occupation")
REPORT_FILE = os.path.join(BASE_DIR, "extraction", "reports", "02_extract_individuals_report.json")
PROGRESS_FILE = os.path.join(OUTPUT_DIR, "reextraction_progress.txt")

# Settings
PAGE_SIZE = 10000
DELAY_BETWEEN_PAGES = 1
ENDPOINT = "https://query.wikidata.org/sparql"
HEADERS = {"Accept": "application/json", "User-Agent": "CulturaDatabase/1.0"}


def log(msg):
    print(msg, flush=True)


def update_progress(occ_name, occ_num, total_occ, current_count, status="fetching"):
    content = f"""Re-extraction Progress
======================
Occupation: {occ_name} [{occ_num}/{total_occ}]
Individuals fetched: {current_count:,}
Status: {status}
Updated: {datetime.now().strftime('%H:%M:%S')}
"""
    with open(PROGRESS_FILE, "w") as f:
        f.write(content)


def clean_json(s):
    """Remove control characters that break JSON parsing."""
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', s)


def sparql_query(query: str) -> list[dict]:
    """Execute SPARQL query with cursor-based pagination."""
    for attempt in range(3):
        try:
            response = requests.get(
                ENDPOINT,
                params={"query": query},
                headers=HEADERS,
                timeout=120
            )
            response.raise_for_status()

            # Clean and parse JSON
            cleaned = clean_json(response.text)
            data = json.loads(cleaned)
            return data["results"]["bindings"]

        except Exception as e:
            if attempt < 2:
                wait = 30 * (attempt + 1)
                log(f"    Error (attempt {attempt+1}): {str(e)[:50]}. Retry in {wait}s...")
                time.sleep(wait)
            else:
                raise


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


def get_partial(occ_id: str) -> tuple:
    """Get partial results and last item cursor."""
    filepath = os.path.join(OCCUPATION_DIR, f"{occ_id}.json")
    if os.path.exists(filepath):
        try:
            with open(filepath) as f:
                data = json.load(f)
            if data.get("partial") and data.get("results"):
                last_cursor = data.get("last_cursor", "")
                return data["results"], last_cursor
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


def fetch_occupation(occ_id: str, occ_name: str, occ_num: int, total_occ: int):
    """Fetch all individuals using cursor-based pagination."""
    all_results, last_cursor = get_partial(occ_id)

    if last_cursor:
        log(f"  Resuming from cursor (already have {len(all_results):,})")

    page = len(all_results) // PAGE_SIZE + 1

    while True:
        # Build filter clause for cursor pagination
        if last_cursor:
            filter_clause = f"FILTER(?item > <{last_cursor}>)"
        else:
            filter_clause = ""

        log(f"  Page {page}: fetching...")
        update_progress(occ_name, occ_num, total_occ, len(all_results), f"page {page}")

        query = f"""
        SELECT ?item ?itemLabel WHERE {{
          ?item wdt:P106 wd:{occ_id} .
          {filter_clause}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
        }}
        ORDER BY ?item
        LIMIT {PAGE_SIZE}
        """

        try:
            results = sparql_query(query)

            if not results:
                log(f"  DONE! Total: {len(all_results):,}")
                update_progress(occ_name, occ_num, total_occ, len(all_results), "complete")
                save_result(occ_id, occ_name, all_results)
                return len(all_results), None

            # Extract data from results
            for r in results:
                item_url = r.get("item", {}).get("value", "")
                wikidata_id = item_url.split("/")[-1] if item_url else ""
                if wikidata_id:
                    all_results.append({
                        "wikidata_id": wikidata_id,
                        "name": r.get("itemLabel", {}).get("value", ""),
                    })

            # Update cursor to last item
            last_cursor = results[-1]["item"]["value"]

            log(f"  Page {page}: +{len(results):,} = {len(all_results):,}")
            update_progress(occ_name, occ_num, total_occ, len(all_results), f"page {page} done")

            # Save progress with cursor
            save_result(occ_id, occ_name, all_results, partial=True, last_cursor=last_cursor)

            if len(results) < PAGE_SIZE:
                log(f"  DONE! Total: {len(all_results):,}")
                update_progress(occ_name, occ_num, total_occ, len(all_results), "complete")
                save_result(occ_id, occ_name, all_results)
                return len(all_results), None

            page += 1
            time.sleep(DELAY_BETWEEN_PAGES)

        except Exception as e:
            log(f"  ERROR: {str(e)[:60]}")
            save_result(occ_id, occ_name, all_results, error=str(e), partial=True, last_cursor=last_cursor)
            return len(all_results), str(e)


def main():
    if not os.path.exists(REPORT_FILE):
        log(f"Report not found: {REPORT_FILE}")
        return

    with open(REPORT_FILE) as f:
        report = json.load(f)

    failed = report.get("errors", [])
    log(f"Failed in report: {len(failed)}")

    to_process = []
    for occ in failed:
        if is_complete(occ["occupation_id"]):
            log(f"SKIP {occ['occupation_name']} - complete")
        else:
            to_process.append(occ)

    if not to_process:
        log("All done!")
        return

    log(f"\nProcessing {len(to_process)} occupations (cursor pagination, {PAGE_SIZE:,}/page)\n")

    results = []
    start = datetime.now()

    for i, occ in enumerate(to_process, 1):
        log(f"\n[{i}/{len(to_process)}] {occ['occupation_name']} ({occ['occupation_id']})")
        count, error = fetch_occupation(occ["occupation_id"], occ["occupation_name"], i, len(to_process))
        results.append({"name": occ["occupation_name"], "count": count, "error": error})

    duration = (datetime.now() - start).total_seconds()
    ok = sum(1 for r in results if r["error"] is None)
    total = sum(r["count"] for r in results)

    log(f"\n{'='*50}")
    log(f"DONE in {duration:.0f}s - {ok}/{len(to_process)} complete")
    log(f"Total individuals: {total:,}")


if __name__ == "__main__":
    main()
