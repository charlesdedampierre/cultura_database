"""Extract all individuals by occupation from Wikidata.

For each occupation from occupations.json, queries Wikidata for all
individuals with that occupation (P106).

Saves one JSON file per occupation in data/extracted/individuals/occupation/
The filename is the occupation ID (e.g., Q12345.json).

Progress is tracked in extraction_progress.txt for easy monitoring.

Outputs:
- data/extracted/individuals/occupation/{occupation_id}.json (one per occupation)
- data/extracted/individuals/individuals.json (final merged)
- data/extracted/individuals/individual_occupations.json (final merged)
- extraction/reports/02_extract_individuals_report.json
"""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from tqdm import tqdm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from wikidata_api import sparql_query

# Paths
BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "extracted", "individuals")
OCCUPATION_DIR = os.path.join(OUTPUT_DIR, "occupation")
REPORT_DIR = os.path.join(BASE_DIR, "extraction", "reports")

# Files
OCCUPATIONS_FILE = os.path.join(OUTPUT_DIR, "occupations.json")
INDIVIDUALS_FILE = os.path.join(OUTPUT_DIR, "individuals.json")
IND_OCC_FILE = os.path.join(OUTPUT_DIR, "individual_occupations.json")
PROGRESS_FILE = os.path.join(OUTPUT_DIR, "extraction_progress.txt")
REPORT_FILE = os.path.join(REPORT_DIR, "02_extract_individuals_report.json")

# Parameters (from speed test: 16 workers optimal, but use 8 to reduce rate limiting)
NUM_WORKERS = 8


def get_individuals_for_occupation(occupation: dict) -> dict:
    """Get all individuals with a given occupation (P106)."""
    occ_id = occupation["occupation_wikidata_id"]
    occ_name = occupation["occupation_name"]

    query = f"""
    SELECT ?item ?itemLabel
    WHERE {{
      ?item wdt:P106 wd:{occ_id} .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language 'en'. }}
    }}
    """

    try:
        rows = sparql_query(query)
        results = []
        for row in rows:
            wikidata_id = row["item"].split("/")[-1]
            results.append({
                "wikidata_id": wikidata_id,
                "name": row.get("itemLabel", ""),
            })
        return {
            "occupation_id": occ_id,
            "occupation_name": occ_name,
            "count": len(results),
            "results": results,
            "error": None,
        }
    except Exception as e:
        return {
            "occupation_id": occ_id,
            "occupation_name": occ_name,
            "count": 0,
            "results": [],
            "error": str(e),
        }


def get_processed_occupations() -> set:
    """Get set of already processed occupation IDs by checking existing files."""
    processed = set()
    if os.path.exists(OCCUPATION_DIR):
        for filename in os.listdir(OCCUPATION_DIR):
            if filename.endswith(".json"):
                processed.add(filename[:-5])  # Remove .json extension
    return processed


def save_occupation_result(result: dict):
    """Save a single occupation result to its own JSON file."""
    occ_id = result["occupation_id"]
    filepath = os.path.join(OCCUPATION_DIR, f"{occ_id}.json")
    with open(filepath, "w") as f:
        json.dump(result, f)


def update_progress_txt(processed: int, total: int, errors: int, start_time: datetime):
    """Update the progress txt file with current status."""
    elapsed = (datetime.now() - start_time).total_seconds()
    speed = processed / elapsed if elapsed > 0 else 0
    remaining = total - processed
    eta_seconds = remaining / speed if speed > 0 else 0
    eta_minutes = eta_seconds / 60

    content = f"""Extraction Progress
==================

Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}
Last update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Progress: {processed:,} / {total:,} occupations ({100*processed/total:.1f}%)
Errors: {errors:,}
Speed: {speed:.2f} occupations/second
ETA: {eta_minutes:.1f} minutes remaining

Output directory: {OCCUPATION_DIR}
Each occupation saved as: {{occupation_id}}.json

If interrupted: Just run the script again - it will resume automatically.
"""
    with open(PROGRESS_FILE, "w") as f:
        f.write(content)


def save_final_output():
    """Merge all occupation files into final individuals and individual_occupations files."""
    individuals = {}
    individual_occupations = []

    # Read all occupation files
    for filename in tqdm(os.listdir(OCCUPATION_DIR), desc="Merging files"):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(OCCUPATION_DIR, filename)
        with open(filepath) as f:
            data = json.load(f)

        occ_id = data["occupation_id"]
        if data["error"] is None:
            for ind in data["results"]:
                wid = ind["wikidata_id"]
                if wid not in individuals:
                    individuals[wid] = {
                        "wikidata_id": wid,
                        "name": ind["name"],
                    }
                individual_occupations.append({
                    "wikidata_id": wid,
                    "occupation_wikidata_id": occ_id,
                })

    # Save individuals
    individuals_list = list(individuals.values())
    with open(INDIVIDUALS_FILE, "w") as f:
        json.dump(individuals_list, f)

    # Save individual-occupations (deduplicated)
    seen = set()
    deduped = []
    for io in individual_occupations:
        key = (io["wikidata_id"], io["occupation_wikidata_id"])
        if key not in seen:
            seen.add(key)
            deduped.append(io)

    with open(IND_OCC_FILE, "w") as f:
        json.dump(deduped, f)

    return len(individuals_list), len(deduped)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(OCCUPATION_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)

    # Load occupations
    with open(OCCUPATIONS_FILE) as f:
        occupations = json.load(f)

    # Get already processed occupations by checking existing files
    processed_ids = get_processed_occupations()

    # Filter remaining occupations
    remaining = [o for o in occupations if o["occupation_wikidata_id"] not in processed_ids]

    print(f"Total occupations: {len(occupations)}")
    print(f"Already processed: {len(processed_ids)}")
    print(f"Remaining: {len(remaining)}")
    print(f"Workers: {NUM_WORKERS}")
    print(f"Output: {OCCUPATION_DIR}")
    print()

    if not remaining:
        print("All occupations already processed!")
        print("Generating final merged files...")
        num_individuals, num_mappings = save_final_output()
        print(f"Total individuals: {num_individuals:,}")
        print(f"Total mappings: {num_mappings:,}")
        return

    # Track results for report
    report_results = []
    start_time = datetime.now()
    processed_count = len(processed_ids)
    total_count = len(occupations)
    error_count = 0

    # Process with thread pool
    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
        futures = {executor.submit(get_individuals_for_occupation, occ): occ for occ in remaining}

        for future in tqdm(as_completed(futures), total=len(remaining), desc="Extracting"):
            result = future.result()
            occ_id = result["occupation_id"]

            # Add to report
            report_results.append({
                "occupation_id": occ_id,
                "occupation_name": result["occupation_name"],
                "count": result["count"],
                "error": result["error"],
            })

            if result["error"] is not None:
                error_count += 1

            # Save this occupation's result to its own JSON file
            save_occupation_result(result)

            # Update progress count and txt file
            processed_count += 1
            update_progress_txt(processed_count, total_count, error_count, start_time)

    # Save final merged output
    print()
    print("Merging occupation files into final output...")
    num_individuals, num_mappings = save_final_output()

    # Clean up progress file
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)

    # Generate report
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    ok_count = sum(1 for r in report_results if r["error"] is None)
    error_count = sum(1 for r in report_results if r["error"] is not None)

    report = {
        "script": "02_extract_individuals.py",
        "started_at": start_time.isoformat(),
        "finished_at": end_time.isoformat(),
        "duration_seconds": duration,
        "parameters": {
            "workers": NUM_WORKERS,
        },
        "summary": {
            "total_occupations": len(occupations),
            "processed_this_run": len(remaining),
            "ok": ok_count,
            "errors": error_count,
            "total_individuals": num_individuals,
            "total_mappings": num_mappings,
        },
        "errors": [r for r in report_results if r["error"] is not None],
    }

    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=2)

    # Print summary
    print()
    print("=" * 60)
    print("EXTRACTION COMPLETE")
    print("=" * 60)
    print(f"Duration: {duration:.0f}s")
    print(f"Occupations processed: {len(remaining)} (OK: {ok_count}, Errors: {error_count})")
    print(f"Total individuals: {num_individuals:,}")
    print(f"Total mappings: {num_mappings:,}")
    print(f"Report: {REPORT_FILE}")


if __name__ == "__main__":
    main()
