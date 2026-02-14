"""
Retry extraction for failed IDs using QLever endpoint.
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from tqdm import tqdm

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

NUM_THREADS = 15
OUTPUT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "extracted", "individuals_qlever"
)

FAILED_IDS_FILE = os.path.join(OUTPUT_DIR, "failed_ids.json")
RETRY_OUTPUT_FILE = os.path.join(OUTPUT_DIR, "retry_results.json")
FINAL_FAILURES_FILE = os.path.join(OUTPUT_DIR, "final_failures.json")


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


def get_full_info(wiki_id: str) -> dict:
    """Get all info for an individual."""
    basic = get_basic_info(wiki_id)
    if not basic:
        return {"wikidata_id": wiki_id, "error": "no basic info"}
    if "error" in basic:
        return basic

    basic["sitelinks"] = get_sitelinks(wiki_id)
    basic["identifiers"] = []  # QLever doesn't support this query
    return basic


def main():
    print(f"Loading failed IDs from {FAILED_IDS_FILE}...")
    with open(FAILED_IDS_FILE, "r") as f:
        failed_ids = json.load(f)

    print(f"Total failed IDs to retry: {len(failed_ids):,}")

    # Set QLever endpoint
    set_endpoint(QLEVER_ENDPOINT)
    print(f"Using endpoint: {QLEVER_ENDPOINT}")

    successful = []
    still_failed = []

    start_time = time.time()

    print(f"Starting retry with {NUM_THREADS} threads...")

    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        future_to_id = {executor.submit(get_full_info, id): id for id in failed_ids}

        for future in tqdm(as_completed(future_to_id), total=len(failed_ids), desc="Retrying"):
            wiki_id = future_to_id[future]
            try:
                result = future.result()
                if result and "error" not in result:
                    successful.append(result)
                else:
                    still_failed.append({
                        "wikidata_id": wiki_id,
                        "error": result.get("error", "unknown") if result else "null result"
                    })
            except Exception as e:
                still_failed.append({
                    "wikidata_id": wiki_id,
                    "error": str(e)
                })

    elapsed = time.time() - start_time

    # Save results
    if successful:
        with open(RETRY_OUTPUT_FILE, "w") as f:
            json.dump(successful, f)
        print(f"\nSaved {len(successful):,} successful extractions to {RETRY_OUTPUT_FILE}")

    if still_failed:
        with open(FINAL_FAILURES_FILE, "w") as f:
            json.dump(still_failed, f, indent=2)
        print(f"Saved {len(still_failed):,} final failures to {FINAL_FAILURES_FILE}")

    print("\n" + "=" * 60)
    print("RETRY COMPLETE")
    print("=" * 60)
    print(f"Total retried: {len(failed_ids):,}")
    print(f"Successful: {len(successful):,}")
    print(f"Still failed: {len(still_failed):,}")
    print(f"Time: {elapsed:.1f}s")
    print(f"Rate: {len(failed_ids)/elapsed:.1f}/s")


if __name__ == "__main__":
    main()
