"""
Fetch modern country data from QLever: id, name, continent, iso_a3_code.
Only includes countries that have an ISO 3166-1 alpha-3 code (P298).
Also fetches English Wikipedia sitelinks for each country.
"""

import json
import requests
from tqdm import tqdm

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"

# Query for sovereign states and countries with ISO alpha-3 codes
QUERY = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?country ?countryLabel ?iso3 ?continent ?continentLabel WHERE {
  ?country wdt:P298 ?iso3 .
  ?country rdfs:label ?countryLabel .
  FILTER(LANG(?countryLabel) = 'en')
  OPTIONAL {
    ?country wdt:P30 ?continent .
    ?continent rdfs:label ?continentLabel .
    FILTER(LANG(?continentLabel) = 'en')
  }
}
"""

SITELINK_QUERY = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX schema: <http://schema.org/>

SELECT ?country ?article WHERE {
  ?country wdt:P298 ?iso3 .
  ?article schema:about ?country .
  ?article schema:isPartOf <https://en.wikipedia.org/> .
}
"""

OUTPUT_FILE = "data/all_humans/modern_countries.json"
ERROR_FILE = "data/all_humans/modern_countries_errors.json"
TASK_LOG = "task.log"


def log(msg):
    with open(TASK_LOG, "a") as f:
        f.write(msg + "\n")
    print(msg)


def extract_qid(uri: str) -> str:
    if "/Q" in uri:
        return uri.split("/")[-1].rstrip(">")
    return uri


def clean_label(label: str) -> str:
    if label.endswith('@en'):
        label = label[:-3]
    return label.strip('"')


def fetch_modern_countries():
    log("[EXTRACTION] Fetching modern countries from QLever...")

    # Step 1: Fetch country data
    params = {"query": QUERY, "action": "tsv_export"}
    response = requests.get(QLEVER_ENDPOINT, params=params, stream=True)
    response.raise_for_status()

    countries = {}
    errors = []

    lines = response.iter_lines(decode_unicode=True)
    header = next(lines)

    for line in tqdm(lines, desc="Parsing countries", unit=" rows"):
        if line:
            try:
                parts = line.strip().split("\t")
                if len(parts) >= 3:
                    country_id = extract_qid(parts[0])
                    country_name = clean_label(parts[1])
                    iso3 = parts[2].strip('"')

                    # Only keep valid ISO 3166-1 alpha-3 codes (3 uppercase letters)
                    if len(iso3) == 3 and iso3.isalpha():
                        iso3 = iso3.upper()
                    else:
                        continue

                    continent_id = None
                    continent_name = None
                    if len(parts) >= 5 and parts[3] and parts[4]:
                        continent_id = extract_qid(parts[3])
                        continent_name = clean_label(parts[4])

                    # Keep first entry per country (most have single continent)
                    if country_id not in countries:
                        countries[country_id] = {
                            "id": country_id,
                            "name": country_name,
                            "iso_a3_code": iso3,
                            "continent_id": continent_id,
                            "continent": continent_name
                        }
            except Exception as e:
                errors.append({"line": line, "error": str(e)})

    log(f"[EXTRACTION] Found {len(countries)} countries with ISO alpha-3 codes")

    # Step 2: Fetch English Wikipedia sitelinks
    log("[EXTRACTION] Fetching English Wikipedia sitelinks for countries...")
    try:
        params = {"query": SITELINK_QUERY, "action": "tsv_export"}
        resp = requests.get(QLEVER_ENDPOINT, params=params, stream=True)
        resp.raise_for_status()

        lines = resp.iter_lines(decode_unicode=True)
        header = next(lines)

        sitelink_count = 0
        for line in tqdm(lines, desc="Parsing country sitelinks", unit=" rows"):
            if line:
                parts = line.strip().split("\t")
                if len(parts) >= 2:
                    country_id = extract_qid(parts[0])
                    url = parts[1].strip("<>")
                    if country_id in countries:
                        countries[country_id]["en_wikipedia_url"] = url
                        sitelink_count += 1

        log(f"[EXTRACTION] Found {sitelink_count} country Wikipedia sitelinks")
    except Exception as e:
        errors.append({"step": "sitelinks", "error": str(e)})
        log(f"[EXTRACTION] Error fetching sitelinks: {e}")

    # Retry errors
    if errors:
        log(f"[EXTRACTION] {len(errors)} errors, saving to {ERROR_FILE}")
        with open(ERROR_FILE, "w") as f:
            json.dump(errors, f, indent=2)

    # Show continent distribution
    continent_counts = {}
    for c in countries.values():
        cont = c.get("continent") or "Unknown"
        continent_counts[cont] = continent_counts.get(cont, 0) + 1

    log("\nContinent distribution:")
    for cont, cnt in sorted(continent_counts.items(), key=lambda x: -x[1]):
        log(f"  {cont}: {cnt}")

    with open(OUTPUT_FILE, "w") as f:
        json.dump(countries, f, indent=2, ensure_ascii=False)

    log(f"[EXTRACTION] Saved {len(countries)} modern countries to {OUTPUT_FILE}")
    return countries


if __name__ == "__main__":
    fetch_modern_countries()
