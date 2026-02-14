"""
Extract full biographical info for ALL individuals from Wikidata.

Features:
- Threading with optimal worker count
- Checkpointing every N individuals (saves progress)
- Resume from last checkpoint if interrupted
- Progress logging to txt file
- Final report of all failures

Output:
- data/extracted/individuals/all_individuals_info.json (final results)
- data/extracted/individuals/extraction_progress.txt (live progress)
- data/extracted/individuals/extraction_checkpoint.json (resume point)
- data/extracted/individuals/extraction_failures.json (failed IDs)
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from threading import Lock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from wikidata_api import sparql_query

# Configuration
NUM_THREADS = 15
CHECKPOINT_EVERY = 10000  # Save progress every N individuals
BATCH_SIZE = 50  # Process in batches for progress updates

OUTPUT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "extracted", "individuals"
)
CHECKPOINT_DIR = os.path.join(OUTPUT_DIR, "individuals_checkpoints")

# File paths
CHECKPOINT_FILE = os.path.join(CHECKPOINT_DIR, "checkpoint_status.json")
PROGRESS_FILE = os.path.join(OUTPUT_DIR, "extraction_progress.txt")
RESULTS_FILE = os.path.join(OUTPUT_DIR, "all_individuals_info.json")
FAILURES_FILE = os.path.join(OUTPUT_DIR, "extraction_failures.json")

# Thread-safe counters
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


def get_basic_info(wiki_id: str) -> dict | None:
    """Get biographical info for a single individual."""
    query = """
    SELECT ?label ?genderLabel ?birthdateLabel ?deathdateLabel ?floruitLabel
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
      OPTIONAL { wd:%s wdt:P21 ?gender. }
      OPTIONAL { wd:%s wdt:P569 ?birthdate. }
      OPTIONAL { wd:%s wdt:P570 ?deathdate. }
      OPTIONAL { wd:%s wdt:P1317 ?floruit. }
      OPTIONAL { wd:%s wdt:P27 ?nationality. }
      OPTIONAL { wd:%s wdt:P19 ?birthcity. }
      OPTIONAL { wd:%s wdt:P20 ?deathcity. }
      OPTIONAL { wd:%s wdt:P6886 ?writingLang. }
      OPTIONAL { wd:%s wdt:P39 ?position. }
      OPTIONAL { wd:%s wdt:P3716 ?socialClass. }
      OPTIONAL { wd:%s wdt:P2348 ?timePeriod. }
      OPTIONAL { wd:%s wdt:P1196 ?mannerOfDeath. }
      OPTIONAL { wd:%s wdt:P101 ?fieldOfWork. }
      OPTIONAL { wd:%s wdt:P106 ?occupation. }
      SERVICE wikibase:label { bd:serviceParam wikibase:language 'en'. }
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
            if row.get("birthdateLabel"):
                birthdates.add(row["birthdateLabel"])
            if row.get("deathdateLabel"):
                deathdates.add(row["deathdateLabel"])
            if row.get("floruitLabel"):
                floruits.add(row["floruitLabel"])
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
    """Get all sitelinks for an individual."""
    query = """
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
    """Get all external identifiers for an individual."""
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
        return identifiers
    except:
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


def load_checkpoint() -> dict:
    """Load checkpoint if exists."""
    result = {"processed_ids": set(), "last_index": 0, "last_checkpoint_num": 0}

    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r") as f:
            checkpoint = json.load(f)
            result["last_index"] = checkpoint.get("last_index", 0)
            result["last_checkpoint_num"] = checkpoint.get("last_checkpoint_num", 0)

    # Load processed IDs from separate file
    ids_file = os.path.join(CHECKPOINT_DIR, "processed_ids.json")
    if os.path.exists(ids_file):
        with open(ids_file, "r") as f:
            result["processed_ids"] = set(json.load(f))

    return result


def save_checkpoint(processed_ids: set, last_index: int, results: list, failures: list, checkpoint_num: int):
    """Save checkpoint and intermediate results."""
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)

    # Save checkpoint status
    checkpoint = {
        "processed_count": len(processed_ids),
        "last_index": last_index,
        "last_checkpoint_num": checkpoint_num,
        "timestamp": datetime.now().isoformat()
    }
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(checkpoint, f, indent=2)

    # Save this batch of results as a separate file
    if results:
        batch_file = os.path.join(CHECKPOINT_DIR, f"batch_{checkpoint_num:04d}.json")
        with open(batch_file, "w") as f:
            json.dump(results, f)
        log_progress(f"    Saved {len(results)} results to batch_{checkpoint_num:04d}.json")

    # Save processed IDs (for resume)
    ids_file = os.path.join(CHECKPOINT_DIR, "processed_ids.json")
    with open(ids_file, "w") as f:
        json.dump(list(processed_ids), f)

    # Save failures
    with open(FAILURES_FILE, "w") as f:
        json.dump(failures, f, indent=2)


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
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)

    # Clear progress file at start (or append if resuming)
    checkpoint = load_checkpoint()
    processed_ids = checkpoint.get("processed_ids", set())
    checkpoint_num = checkpoint.get("last_checkpoint_num", 0)

    if not processed_ids:
        with open(PROGRESS_FILE, "w") as f:
            f.write("=" * 60 + "\n")
            f.write("FULL EXTRACTION STARTED\n")
            f.write("=" * 60 + "\n\n")
    log_progress("Loading individual IDs from database...")
    all_ids = load_all_individual_ids()
    total = len(all_ids)
    log_progress(f"Total individuals to extract: {total:,}")

    if processed_ids:
        log_progress(f"Resuming from checkpoint: {len(processed_ids):,} already processed")

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
    log_progress(f"Checkpoint every {CHECKPOINT_EVERY:,} individuals")
    log_progress(f"Saving to: {CHECKPOINT_DIR}")

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

            # Checkpoint every N
            if processed_count % CHECKPOINT_EVERY == 0:
                checkpoint_num += 1
                all_failures.extend(batch_failures)
                save_checkpoint(processed_ids, processed_count, batch_results, all_failures, checkpoint_num)
                log_progress(f">>> CHECKPOINT {checkpoint_num} SAVED at {processed_count:,}")
                batch_results = []
                batch_failures = []

    # Final save
    if batch_results or batch_failures:
        checkpoint_num += 1
        all_failures.extend(batch_failures)
        save_checkpoint(processed_ids, processed_count, batch_results, all_failures, checkpoint_num)
        log_progress(f">>> FINAL CHECKPOINT {checkpoint_num} SAVED")

    # Final report
    elapsed = time.time() - start_time
    log_progress("\n" + "=" * 60)
    log_progress("EXTRACTION COMPLETE")
    log_progress("=" * 60)
    log_progress(f"Total processed: {processed_count:,}")
    log_progress(f"Successful: {processed_count - len(all_failures):,}")
    log_progress(f"Failures: {len(all_failures):,}")
    log_progress(f"Total time: {elapsed/3600:.2f} hours")
    log_progress(f"Average rate: {(processed_count - initial_count)/elapsed:.1f} individuals/sec")
    log_progress(f"\nCheckpoint batches saved to: {CHECKPOINT_DIR}")
    log_progress(f"Total batch files: {checkpoint_num}")
    log_progress(f"Failures saved to: {FAILURES_FILE}")
    log_progress(f"Progress log: {PROGRESS_FILE}")

    # Count total results in batch files
    total_results = 0
    for i in range(1, checkpoint_num + 1):
        batch_file = os.path.join(CHECKPOINT_DIR, f"batch_{i:04d}.json")
        if os.path.exists(batch_file):
            with open(batch_file, "r") as f:
                total_results += len(json.load(f))
    log_progress(f"Total results in batches: {total_results:,}")


if __name__ == "__main__":
    main()
