"""
Optimized extraction: 3 batched queries + multiprocessing.
Target: 50+ individuals/second.

Strategy:
- Batch 50 individuals per SPARQL query (using VALUES clause)
- 3 queries per batch: basic info, sitelinks, identifiers
- Multiprocessing for parallel batch processing
- Minimal delay between requests
"""

import json
import os
import sys
import time
from multiprocessing import Pool
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from wikidata_api import sparql_query

# Configuration
NUM_WORKERS = 8  # Parallel batch processors
BATCH_SIZE = 50  # Individuals per SPARQL query
CHECKPOINT_EVERY = 10000  # Save progress every N individuals
TEST_LIMIT = 500  # Set to None for full extraction

OUTPUT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "extracted", "individuals"
)
CHECKPOINT_DIR = os.path.join(OUTPUT_DIR, "individuals_checkpoints")
PROGRESS_FILE = os.path.join(OUTPUT_DIR, "extraction_progress.txt")
FAILURES_FILE = os.path.join(OUTPUT_DIR, "extraction_failures.json")


def log_progress(message: str):
    """Log progress to file and console."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}"
    print(log_line)
    try:
        with open(PROGRESS_FILE, "a") as f:
            f.write(log_line + "\n")
    except:
        pass


def get_batch_basic_info(wiki_ids: list) -> dict:
    """Get basic info for a batch of individuals."""
    values = " ".join([f"wd:{id}" for id in wiki_ids])

    query = f"""
    SELECT ?item ?itemLabel ?genderLabel ?birthdateLabel ?deathdateLabel ?floruitLabel
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
    WHERE {{
      VALUES ?item {{ {values} }}
      OPTIONAL {{ ?item rdfs:label ?itemLabel. FILTER(LANG(?itemLabel) = 'en') }}
      OPTIONAL {{ ?item schema:description ?description. }}
      OPTIONAL {{ ?item wdt:P21 ?gender. }}
      OPTIONAL {{ ?item wdt:P569 ?birthdate. }}
      OPTIONAL {{ ?item wdt:P570 ?deathdate. }}
      OPTIONAL {{ ?item wdt:P1317 ?floruit. }}
      OPTIONAL {{ ?item wdt:P27 ?nationality. }}
      OPTIONAL {{ ?item wdt:P19 ?birthcity. }}
      OPTIONAL {{ ?item wdt:P20 ?deathcity. }}
      OPTIONAL {{ ?item wdt:P6886 ?writingLang. }}
      OPTIONAL {{ ?item wdt:P39 ?position. }}
      OPTIONAL {{ ?item wdt:P3716 ?socialClass. }}
      OPTIONAL {{ ?item wdt:P2348 ?timePeriod. }}
      OPTIONAL {{ ?item wdt:P1196 ?mannerOfDeath. }}
      OPTIONAL {{ ?item wdt:P101 ?fieldOfWork. }}
      OPTIONAL {{ ?item wdt:P106 ?occupation. }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language 'en'. }}
    }}
    """

    try:
        rows = sparql_query(query)
        return {"success": True, "rows": rows}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_batch_sitelinks(wiki_ids: list) -> dict:
    """Get sitelinks for a batch of individuals."""
    values = " ".join([f"wd:{id}" for id in wiki_ids])

    query = f"""
    SELECT ?item ?sitelink ?siteName WHERE {{
      VALUES ?item {{ {values} }}
      ?sitelink schema:about ?item .
      ?sitelink schema:isPartOf ?site .
      ?sitelink schema:name ?siteName .
      FILTER(CONTAINS(STR(?sitelink), "wikipedia.org"))
    }}
    """

    try:
        rows = sparql_query(query)
        return {"success": True, "rows": rows}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_batch_identifiers(wiki_ids: list) -> dict:
    """Get identifiers for a batch of individuals."""
    values = " ".join([f"wd:{id}" for id in wiki_ids])

    query = f"""
    SELECT ?item ?prop ?propLabel ?value WHERE {{
      VALUES ?item {{ {values} }}
      ?item ?p ?value .
      ?prop wikibase:directClaim ?p .
      ?prop wikibase:propertyType wikibase:ExternalId .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language 'en'. }}
    }}
    """

    try:
        rows = sparql_query(query)
        return {"success": True, "rows": rows}
    except Exception as e:
        return {"success": False, "error": str(e)}


def process_batch(wiki_ids: list) -> list:
    """Process a batch of individuals - 3 batched queries."""

    # Initialize data for each ID
    data = {id: {
        "wikidata_id": id,
        "name": None,
        "descriptions": {},
        "gender": set(),
        "birthdates": set(),
        "deathdates": set(),
        "floruits": set(),
        "nationalities": [],
        "birthcities": [],
        "deathcities": [],
        "writing_languages": [],
        "positions_held": [],
        "social_classifications": [],
        "time_periods": [],
        "manners_of_death": [],
        "fields_of_work": [],
        "occupations": [],
        "sitelinks": [],
        "identifiers": []
    } for id in wiki_ids}

    # Query 1: Basic info
    basic_result = get_batch_basic_info(wiki_ids)
    if not basic_result["success"]:
        return [{"wikidata_id": id, "error": basic_result.get("error", "basic query failed")} for id in wiki_ids]

    for row in basic_result["rows"]:
        item_uri = row.get("item", "")
        wiki_id = item_uri.split("/")[-1] if "/" in item_uri else None
        if not wiki_id or wiki_id not in data:
            continue

        d = data[wiki_id]
        if row.get("itemLabel"):
            d["name"] = row["itemLabel"]
        if row.get("genderLabel"):
            d["gender"].add(row["genderLabel"])
        if row.get("birthdateLabel"):
            d["birthdates"].add(row["birthdateLabel"])
        if row.get("deathdateLabel"):
            d["deathdates"].add(row["deathdateLabel"])
        if row.get("floruitLabel"):
            d["floruits"].add(row["floruitLabel"])
        if row.get("description"):
            lang = row.get("descLang", "unknown")
            d["descriptions"][lang] = row["description"]

        # Multi-valued properties
        if row.get("nationality"):
            nat_id = row["nationality"].split("/")[-1]
            d["nationalities"].append({"wikidata_id": nat_id, "name": row.get("nationalityLabel", "")})
        if row.get("birthcity"):
            bc_id = row["birthcity"].split("/")[-1]
            d["birthcities"].append({"wikidata_id": bc_id, "name": row.get("birthcityLabel", "")})
        if row.get("deathcity"):
            dc_id = row["deathcity"].split("/")[-1]
            d["deathcities"].append({"wikidata_id": dc_id, "name": row.get("deathcityLabel", "")})
        if row.get("writingLang"):
            wl_id = row["writingLang"].split("/")[-1]
            d["writing_languages"].append({"wikidata_id": wl_id, "name": row.get("writingLangLabel", "")})
        if row.get("position"):
            pos_id = row["position"].split("/")[-1]
            d["positions_held"].append({"wikidata_id": pos_id, "name": row.get("positionLabel", "")})
        if row.get("socialClass"):
            sc_id = row["socialClass"].split("/")[-1]
            d["social_classifications"].append({"wikidata_id": sc_id, "name": row.get("socialClassLabel", "")})
        if row.get("timePeriod"):
            tp_id = row["timePeriod"].split("/")[-1]
            d["time_periods"].append({"wikidata_id": tp_id, "name": row.get("timePeriodLabel", "")})
        if row.get("mannerOfDeath"):
            mod_id = row["mannerOfDeath"].split("/")[-1]
            d["manners_of_death"].append({"wikidata_id": mod_id, "name": row.get("mannerOfDeathLabel", "")})
        if row.get("fieldOfWork"):
            fow_id = row["fieldOfWork"].split("/")[-1]
            d["fields_of_work"].append({"wikidata_id": fow_id, "name": row.get("fieldOfWorkLabel", "")})
        if row.get("occupation"):
            occ_id = row["occupation"].split("/")[-1]
            d["occupations"].append({"wikidata_id": occ_id, "name": row.get("occupationLabel", "")})

    # Query 2: Sitelinks
    sitelinks_result = get_batch_sitelinks(wiki_ids)
    if sitelinks_result["success"]:
        for row in sitelinks_result["rows"]:
            item_uri = row.get("item", "")
            wiki_id = item_uri.split("/")[-1] if "/" in item_uri else None
            if not wiki_id or wiki_id not in data:
                continue

            url = row.get("sitelink", "")
            name = row.get("siteName", "")
            site = url.split("//")[1].split("/")[0] if "//" in url else ""
            data[wiki_id]["sitelinks"].append({"site": site, "title": name, "url": url})

    # Query 3: Identifiers
    identifiers_result = get_batch_identifiers(wiki_ids)
    if identifiers_result["success"]:
        for row in identifiers_result["rows"]:
            item_uri = row.get("item", "")
            wiki_id = item_uri.split("/")[-1] if "/" in item_uri else None
            if not wiki_id or wiki_id not in data:
                continue

            prop_uri = row.get("prop", "")
            prop_id = prop_uri.split("/")[-1] if "/" in prop_uri else prop_uri
            data[wiki_id]["identifiers"].append({
                "property_id": prop_id,
                "property_name": row.get("propLabel", ""),
                "value": row.get("value", "")
            })

    # Finalize results
    def dedupe(items):
        seen = set()
        result = []
        for item in items:
            if item["wikidata_id"] not in seen:
                seen.add(item["wikidata_id"])
                result.append(item)
        return result or None

    results = []
    for wiki_id, d in data.items():
        result = {
            "wikidata_id": wiki_id,
            "name": d["name"],
            "descriptions": d["descriptions"] or None,
            "gender": list(d["gender"]) if d["gender"] else None,
            "birthdate": list(d["birthdates"])[0] if d["birthdates"] else None,
            "deathdate": list(d["deathdates"])[0] if d["deathdates"] else None,
            "floruit": list(d["floruits"])[0] if d["floruits"] else None,
            "nationalities": dedupe(d["nationalities"]),
            "birthcities": dedupe(d["birthcities"]),
            "deathcities": dedupe(d["deathcities"]),
            "writing_languages": dedupe(d["writing_languages"]),
            "positions_held": dedupe(d["positions_held"]),
            "social_classifications": dedupe(d["social_classifications"]),
            "time_periods": dedupe(d["time_periods"]),
            "manners_of_death": dedupe(d["manners_of_death"]),
            "fields_of_work": dedupe(d["fields_of_work"]),
            "occupations": dedupe(d["occupations"]),
            "sitelinks": d["sitelinks"] if d["sitelinks"] else [],
            "identifiers": d["identifiers"] if d["identifiers"] else []
        }
        results.append(result)

    return results


def process_batch_wrapper(batch_data):
    """Wrapper for multiprocessing."""
    batch_index, wiki_ids = batch_data
    try:
        results = process_batch(wiki_ids)
        return {"batch_index": batch_index, "results": results}
    except Exception as e:
        return {
            "batch_index": batch_index,
            "results": [{"wikidata_id": id, "error": str(e)} for id in wiki_ids]
        }


def load_checkpoint() -> dict:
    """Load checkpoint if exists."""
    checkpoint_file = os.path.join(CHECKPOINT_DIR, "checkpoint_status.json")
    ids_file = os.path.join(CHECKPOINT_DIR, "processed_ids.json")

    result = {"processed_ids": set(), "last_checkpoint_num": 0}

    if os.path.exists(checkpoint_file):
        with open(checkpoint_file, "r") as f:
            checkpoint = json.load(f)
            result["last_checkpoint_num"] = checkpoint.get("last_checkpoint_num", 0)

    if os.path.exists(ids_file):
        with open(ids_file, "r") as f:
            result["processed_ids"] = set(json.load(f))

    return result


def save_checkpoint(processed_ids: set, results: list, failures: list, checkpoint_num: int):
    """Save checkpoint."""
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)

    checkpoint_file = os.path.join(CHECKPOINT_DIR, "checkpoint_status.json")
    with open(checkpoint_file, "w") as f:
        json.dump({
            "processed_count": len(processed_ids),
            "last_checkpoint_num": checkpoint_num,
            "timestamp": datetime.now().isoformat()
        }, f, indent=2)

    if results:
        batch_file = os.path.join(CHECKPOINT_DIR, f"batch_{checkpoint_num:04d}.json")
        with open(batch_file, "w") as f:
            json.dump(results, f)
        log_progress(f"    Saved {len(results)} results to batch_{checkpoint_num:04d}.json")

    ids_file = os.path.join(CHECKPOINT_DIR, "processed_ids.json")
    with open(ids_file, "w") as f:
        json.dump(list(processed_ids), f)

    with open(FAILURES_FILE, "w") as f:
        json.dump(failures, f, indent=2)


def load_all_individual_ids() -> list:
    """Load all individual IDs from database."""
    import sqlite3
    db_path = os.path.join(os.path.dirname(__file__), "..", "..", "cultura_database.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT wikidata_id FROM individuals")
    ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    return ids


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)

    checkpoint = load_checkpoint()
    processed_ids = checkpoint["processed_ids"]
    checkpoint_num = checkpoint["last_checkpoint_num"]

    if not processed_ids:
        with open(PROGRESS_FILE, "w") as f:
            f.write("=" * 60 + "\n")
            f.write("BATCHED EXTRACTION (3 queries per batch)\n")
            f.write("=" * 60 + "\n\n")

    log_progress("Loading individual IDs from database...")
    all_ids = load_all_individual_ids()

    if TEST_LIMIT:
        all_ids = all_ids[:TEST_LIMIT]
        log_progress(f"TEST MODE: Limited to {TEST_LIMIT:,} individuals")

    total = len(all_ids)
    log_progress(f"Total individuals: {total:,}")

    if processed_ids:
        log_progress(f"Resuming: {len(processed_ids):,} already processed")

    remaining_ids = [id for id in all_ids if id not in processed_ids]
    log_progress(f"Remaining to process: {len(remaining_ids):,}")

    # Create batches
    batches = []
    for i in range(0, len(remaining_ids), BATCH_SIZE):
        batch = remaining_ids[i:i+BATCH_SIZE]
        batches.append((len(batches), batch))

    log_progress(f"Created {len(batches):,} batches of {BATCH_SIZE} individuals")
    log_progress(f"Using {NUM_WORKERS} parallel workers")

    all_failures = []
    batch_results = []
    start_time = time.time()
    processed_this_session = 0

    with Pool(NUM_WORKERS) as pool:
        for result in pool.imap_unordered(process_batch_wrapper, batches):
            individuals = result["results"]

            for ind in individuals:
                processed_ids.add(ind["wikidata_id"])
                processed_this_session += 1

                if "error" in ind:
                    all_failures.append(ind)
                else:
                    batch_results.append(ind)

            # Progress every 5 batches
            if processed_this_session % (BATCH_SIZE * 5) < BATCH_SIZE:
                elapsed = time.time() - start_time
                rate = processed_this_session / elapsed if elapsed > 0 else 0
                total_processed = len(processed_ids)
                remaining = total - total_processed
                eta_hours = remaining / rate / 3600 if rate > 0 else 0

                log_progress(
                    f"Progress: {total_processed:,}/{total:,} ({100*total_processed/total:.1f}%) | "
                    f"Rate: {rate:.1f}/s | ETA: {eta_hours:.1f}h | "
                    f"OK: {len(batch_results)}, Fail: {len(all_failures)}"
                )

            # Checkpoint
            if len(batch_results) >= CHECKPOINT_EVERY:
                checkpoint_num += 1
                save_checkpoint(processed_ids, batch_results, all_failures, checkpoint_num)
                log_progress(f">>> CHECKPOINT {checkpoint_num} SAVED ({len(processed_ids):,} total)")
                batch_results = []

    # Final checkpoint
    if batch_results:
        checkpoint_num += 1
        save_checkpoint(processed_ids, batch_results, all_failures, checkpoint_num)
        log_progress(f">>> FINAL CHECKPOINT {checkpoint_num} SAVED")

    elapsed = time.time() - start_time
    log_progress("\n" + "=" * 60)
    log_progress("EXTRACTION COMPLETE")
    log_progress("=" * 60)
    log_progress(f"Total processed: {len(processed_ids):,}")
    log_progress(f"Successful: {len(processed_ids) - len(all_failures):,}")
    log_progress(f"Failures: {len(all_failures):,}")
    log_progress(f"Time: {elapsed/3600:.2f} hours")
    log_progress(f"Rate: {processed_this_session/elapsed:.1f} individuals/sec")


if __name__ == "__main__":
    main()
