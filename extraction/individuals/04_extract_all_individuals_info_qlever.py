"""
Extract full biographical info for ALL individuals from Wikidata using QLever endpoint.

Features:
- Threading with optimal worker count
- Checkpointing every N individuals (saves progress)
- Resume from last checkpoint if interrupted
- Progress logging to txt file
- Final report of all failures
- QLever-compatible SPARQL queries (with PREFIX declarations)
- SQLite database output (same schema as sample.db)

Output:
- data/extracted/individuals_qlever/individuals_qlever.db (SQLite database)
- data/extracted/individuals_qlever/extraction_progress.txt (live progress)
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from threading import Lock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from wikidata_api import sparql_query, set_endpoint

# QLever endpoint
QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"

# SPARQL Prefixes for QLever
PREFIXES = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX schema: <http://schema.org/>
PREFIX wikibase: <http://wikiba.se/ontology#>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/>
"""

# Configuration
NUM_THREADS = 15
CHECKPOINT_EVERY = 10000  # Save JSON batch every N individuals
BATCH_SIZE = 50  # Process in batches for progress updates
TEST_LIMIT = None  # Set to None for full extraction

OUTPUT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "extracted", "individuals_qlever"
)
CHECKPOINT_DIR = os.path.join(OUTPUT_DIR, "json_batches")

# File paths
PROGRESS_FILE = os.path.join(OUTPUT_DIR, "extraction_progress.txt")
PROCESSED_IDS_FILE = os.path.join(OUTPUT_DIR, "processed_ids.json")

# Thread-safe counters
results_lock = Lock()
progress_lock = Lock()


def save_batch_to_json(results: list, batch_num: int):
    """Save a batch of results to a JSON file."""
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    batch_file = os.path.join(CHECKPOINT_DIR, f"batch_{batch_num:04d}.json")
    with open(batch_file, "w") as f:
        json.dump(results, f)
    return batch_file


def get_processed_ids() -> set:
    """Get set of already processed IDs from processed_ids file."""
    if not os.path.exists(PROCESSED_IDS_FILE):
        return set()
    with open(PROCESSED_IDS_FILE, "r") as f:
        return set(json.load(f))


def save_processed_ids(processed_ids: set):
    """Save processed IDs to file."""
    with open(PROCESSED_IDS_FILE, "w") as f:
        json.dump(list(processed_ids), f)


def log_progress(message: str):
    """Log progress to file and console."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}"
    print(log_line)
    with progress_lock:
        with open(PROGRESS_FILE, "a") as f:
            f.write(log_line + "\n")


def get_basic_info(wiki_id: str) -> dict | None:
    """Get biographical info for a single individual (QLever-compatible)."""
    query = PREFIXES + """
    SELECT ?label ?gender ?genderLabel ?birthdate ?deathdate ?floruit
           ?nationality ?nationalityLabel
           ?birthcity ?birthcityLabel
           ?deathcity ?deathcityLabel
           ?writingLang ?writingLangLabel
           ?position ?positionLabel
           ?socialClass ?socialClassLabel
           ?timePeriod ?timePeriodLabel
           ?mannerOfDeath ?mannerOfDeathLabel
           ?fieldOfWork ?fieldOfWorkLabel
           ?occupation ?occupationLabel
           ?description (LANG(?description) AS ?descLang)
    WHERE {
      OPTIONAL { wd:%s rdfs:label ?label. FILTER(LANG(?label) = 'en') }
      OPTIONAL { wd:%s schema:description ?description. }
      OPTIONAL { wd:%s wdt:P21 ?gender. OPTIONAL { ?gender rdfs:label ?genderLabel. FILTER(LANG(?genderLabel) = 'en') } }
      OPTIONAL { wd:%s wdt:P569 ?birthdate. }
      OPTIONAL { wd:%s wdt:P570 ?deathdate. }
      OPTIONAL { wd:%s wdt:P1317 ?floruit. }
      OPTIONAL { wd:%s wdt:P27 ?nationality. OPTIONAL { ?nationality rdfs:label ?nationalityLabel. FILTER(LANG(?nationalityLabel) = 'en') } }
      OPTIONAL { wd:%s wdt:P19 ?birthcity. OPTIONAL { ?birthcity rdfs:label ?birthcityLabel. FILTER(LANG(?birthcityLabel) = 'en') } }
      OPTIONAL { wd:%s wdt:P20 ?deathcity. OPTIONAL { ?deathcity rdfs:label ?deathcityLabel. FILTER(LANG(?deathcityLabel) = 'en') } }
      OPTIONAL { wd:%s wdt:P6886 ?writingLang. OPTIONAL { ?writingLang rdfs:label ?writingLangLabel. FILTER(LANG(?writingLangLabel) = 'en') } }
      OPTIONAL { wd:%s wdt:P39 ?position. OPTIONAL { ?position rdfs:label ?positionLabel. FILTER(LANG(?positionLabel) = 'en') } }
      OPTIONAL { wd:%s wdt:P3716 ?socialClass. OPTIONAL { ?socialClass rdfs:label ?socialClassLabel. FILTER(LANG(?socialClassLabel) = 'en') } }
      OPTIONAL { wd:%s wdt:P2348 ?timePeriod. OPTIONAL { ?timePeriod rdfs:label ?timePeriodLabel. FILTER(LANG(?timePeriodLabel) = 'en') } }
      OPTIONAL { wd:%s wdt:P1196 ?mannerOfDeath. OPTIONAL { ?mannerOfDeath rdfs:label ?mannerOfDeathLabel. FILTER(LANG(?mannerOfDeathLabel) = 'en') } }
      OPTIONAL { wd:%s wdt:P101 ?fieldOfWork. OPTIONAL { ?fieldOfWork rdfs:label ?fieldOfWorkLabel. FILTER(LANG(?fieldOfWorkLabel) = 'en') } }
      OPTIONAL { wd:%s wdt:P106 ?occupation. OPTIONAL { ?occupation rdfs:label ?occupationLabel. FILTER(LANG(?occupationLabel) = 'en') } }
    }
    """ % tuple([wiki_id] * 16)

    try:
        rows = sparql_query(query)
        if not rows:
            return None

        label = None
        genders = set()
        birthdates = set()
        deathdates = set()
        floruits = set()
        nationalities = []
        birthcities = []
        deathcities = []
        writing_languages = []
        positions = []
        social_classes = []
        time_periods = []
        manners_of_death = []
        fields_of_work = []
        occupations = []
        descriptions = {}

        for row in rows:
            if row.get("label"):
                label = row["label"]
            if row.get("genderLabel"):
                genders.add(row["genderLabel"])
            if row.get("birthdate"):
                birthdates.add(row["birthdate"])
            if row.get("deathdate"):
                deathdates.add(row["deathdate"])
            if row.get("floruit"):
                floruits.add(row["floruit"])
            if row.get("description"):
                lang = row.get("descLang", "unknown")
                descriptions[lang] = row["description"]
            if row.get("nationality"):
                nat_id = row["nationality"].split("/")[-1]
                nationalities.append({"wikidata_id": nat_id, "name": row.get("nationalityLabel", "")})
            if row.get("birthcity"):
                bc_id = row["birthcity"].split("/")[-1]
                birthcities.append({"wikidata_id": bc_id, "name": row.get("birthcityLabel", "")})
            if row.get("deathcity"):
                dc_id = row["deathcity"].split("/")[-1]
                deathcities.append({"wikidata_id": dc_id, "name": row.get("deathcityLabel", "")})
            if row.get("writingLang"):
                wl_id = row["writingLang"].split("/")[-1]
                writing_languages.append({"wikidata_id": wl_id, "name": row.get("writingLangLabel", "")})
            if row.get("position"):
                pos_id = row["position"].split("/")[-1]
                positions.append({"wikidata_id": pos_id, "name": row.get("positionLabel", "")})
            if row.get("socialClass"):
                sc_id = row["socialClass"].split("/")[-1]
                social_classes.append({"wikidata_id": sc_id, "name": row.get("socialClassLabel", "")})
            if row.get("timePeriod"):
                tp_id = row["timePeriod"].split("/")[-1]
                time_periods.append({"wikidata_id": tp_id, "name": row.get("timePeriodLabel", "")})
            if row.get("mannerOfDeath"):
                mod_id = row["mannerOfDeath"].split("/")[-1]
                manners_of_death.append({"wikidata_id": mod_id, "name": row.get("mannerOfDeathLabel", "")})
            if row.get("fieldOfWork"):
                fow_id = row["fieldOfWork"].split("/")[-1]
                fields_of_work.append({"wikidata_id": fow_id, "name": row.get("fieldOfWorkLabel", "")})
            if row.get("occupation"):
                occ_id = row["occupation"].split("/")[-1]
                occupations.append({"wikidata_id": occ_id, "name": row.get("occupationLabel", "")})

        def dedupe(items):
            seen = set()
            result = []
            for item in items:
                if item["wikidata_id"] not in seen:
                    seen.add(item["wikidata_id"])
                    result.append(item)
            return result or None

        return {
            "wikidata_id": wiki_id,
            "name": label,
            "descriptions": descriptions or None,
            "gender": list(genders) if genders else None,
            "birthdate": list(birthdates)[0] if birthdates else None,
            "deathdate": list(deathdates)[0] if deathdates else None,
            "floruit": list(floruits)[0] if floruits else None,
            "nationalities": dedupe(nationalities),
            "birthcities": dedupe(birthcities),
            "deathcities": dedupe(deathcities),
            "writing_languages": dedupe(writing_languages),
            "positions_held": dedupe(positions),
            "social_classifications": dedupe(social_classes),
            "time_periods": dedupe(time_periods),
            "manners_of_death": dedupe(manners_of_death),
            "fields_of_work": dedupe(fields_of_work),
            "occupations": dedupe(occupations),
        }
    except Exception as e:
        return {"wikidata_id": wiki_id, "error": str(e)}


def get_sitelinks(wiki_id: str) -> list:
    """Get all sitelinks for an individual (QLever-compatible)."""
    query = PREFIXES + """
    SELECT ?sitelink ?siteName WHERE {
      ?sitelink schema:about wd:%s .
      ?sitelink schema:isPartOf ?site .
      ?sitelink schema:name ?siteName .
    }
    """ % wiki_id

    try:
        rows = sparql_query(query)
        sitelinks = []
        for row in rows:
            url = row.get("sitelink", "")
            name = row.get("siteName", "")
            if "wikipedia.org" in url:
                site = url.split("//")[1].split("/")[0] if "//" in url else ""
                sitelinks.append({"site": site, "title": name, "url": url})
        return sitelinks
    except:
        return []


def get_identifiers(wiki_id: str) -> list:
    """Get external identifiers for an individual (QLever-compatible).

    Note: QLever doesn't support wikibase:directClaim/propertyType,
    so we skip this for QLever and return empty list.
    """
    # QLever doesn't support the wikibase ontology queries needed for identifiers
    # Return empty list - identifiers can be fetched separately if needed
    return []


def get_full_info(wiki_id: str) -> dict:
    """Get all info for an individual."""
    basic = get_basic_info(wiki_id)
    if not basic:
        return {"wikidata_id": wiki_id, "error": "no basic info"}
    if "error" in basic:
        return basic

    basic["sitelinks"] = get_sitelinks(wiki_id)
    basic["identifiers"] = get_identifiers(wiki_id)
    return basic


def load_all_individual_ids() -> list:
    """Load all unique individual IDs from the database."""
    import sqlite3
    db_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "cultura_database.db"
    )
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT wikidata_id FROM individuals")
    ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    return ids


def main():
    # Set QLever endpoint
    set_endpoint(QLEVER_ENDPOINT)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)

    # Get already processed IDs (for resume)
    processed_ids = get_processed_ids()

    # Count existing batch files
    existing_batches = len([f for f in os.listdir(CHECKPOINT_DIR) if f.startswith("batch_") and f.endswith(".json")]) if os.path.exists(CHECKPOINT_DIR) else 0
    batch_num = existing_batches

    if not processed_ids:
        with open(PROGRESS_FILE, "w") as f:
            f.write("=" * 60 + "\n")
            f.write("QLEVER EXTRACTION TO JSON\n")
            f.write("=" * 60 + "\n\n")

    log_progress(f"Using endpoint: {QLEVER_ENDPOINT}")
    log_progress("Loading individual IDs from database...")
    all_ids = load_all_individual_ids()

    # Apply test limit if set
    if TEST_LIMIT:
        all_ids = all_ids[:TEST_LIMIT]
        log_progress(f"TEST MODE: Limited to {TEST_LIMIT:,} individuals")

    total = len(all_ids)
    log_progress(f"Total individuals to extract: {total:,}")

    if processed_ids:
        log_progress(f"Resuming from checkpoint: {len(processed_ids):,} already processed ({batch_num} batches)")

    # Filter out already processed
    remaining_ids = [id for id in all_ids if id not in processed_ids]
    log_progress(f"Remaining to process: {len(remaining_ids):,}")

    all_failures = []
    batch_results = []
    batch_failures = []

    start_time = time.time()
    processed_count = len(processed_ids)
    initial_count = processed_count

    log_progress(f"Starting extraction with {NUM_THREADS} threads...")
    log_progress(f"Saving JSON batch every {CHECKPOINT_EVERY:,} individuals")
    log_progress(f"Output directory: {CHECKPOINT_DIR}")

    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        # Submit all tasks
        future_to_id = {executor.submit(get_full_info, id): id for id in remaining_ids}

        for i, future in enumerate(as_completed(future_to_id)):
            wiki_id = future_to_id[future]
            try:
                result = future.result()
                if result and "error" not in result:
                    batch_results.append(result)
                else:
                    batch_failures.append({
                        "wikidata_id": wiki_id,
                        "error": result.get("error", "unknown") if result else "null result"
                    })
            except Exception as e:
                batch_failures.append({
                    "wikidata_id": wiki_id,
                    "error": str(e)
                })

            processed_ids.add(wiki_id)
            processed_count += 1

            # Progress update every 100
            if processed_count % 100 == 0:
                elapsed = time.time() - start_time
                rate = (processed_count - initial_count) / elapsed if elapsed > 0 else 0
                remaining = total - processed_count
                eta_seconds = remaining / rate if rate > 0 else 0
                eta_hours = eta_seconds / 3600

                log_progress(
                    f"Progress: {processed_count:,}/{total:,} ({100*processed_count/total:.1f}%) | "
                    f"Rate: {rate:.1f}/s | ETA: {eta_hours:.1f}h | "
                    f"Batch: {len(batch_results)} ok, {len(batch_failures)} fail"
                )

            # Save to JSON every N
            if processed_count % CHECKPOINT_EVERY == 0:
                batch_num += 1
                all_failures.extend(batch_failures)
                batch_file = save_batch_to_json(batch_results, batch_num)
                save_processed_ids(processed_ids)
                log_progress(f">>> SAVED batch_{batch_num:04d}.json ({len(batch_results):,} records) at {processed_count:,}")
                batch_results = []
                batch_failures = []

    # Final save
    if batch_results:
        batch_num += 1
        all_failures.extend(batch_failures)
        batch_file = save_batch_to_json(batch_results, batch_num)
        save_processed_ids(processed_ids)
        log_progress(f">>> FINAL SAVE: batch_{batch_num:04d}.json ({len(batch_results):,} records)")

    # Final report
    elapsed = time.time() - start_time
    log_progress("\n" + "=" * 60)
    log_progress("EXTRACTION COMPLETE")
    log_progress("=" * 60)
    log_progress(f"Total processed: {processed_count:,}")
    log_progress(f"Successful: {processed_count - len(all_failures):,}")
    log_progress(f"Failures: {len(all_failures):,}")
    log_progress(f"Total time: {elapsed/3600:.2f} hours")
    if elapsed > 0:
        log_progress(f"Average rate: {(processed_count - initial_count)/elapsed:.1f} individuals/sec")
    log_progress(f"\nJSON batches saved to: {CHECKPOINT_DIR}")
    log_progress(f"Total batch files: {batch_num}")
    log_progress(f"Progress log: {PROGRESS_FILE}")


if __name__ == "__main__":
    main()
