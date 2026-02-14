"""
Fetch all Q5 (human) writing languages (P6886) with English labels using QLever bulk query.
Saves errors and retries once for failed rows.
"""

import json
import requests
from tqdm import tqdm
from collections import defaultdict
import os

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"

QUERY = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?human ?lang ?langLabel WHERE {
  ?human wdt:P31 wd:Q5 .
  ?human wdt:P6886 ?lang .
  ?lang rdfs:label ?langLabel .
  FILTER(LANG(?langLabel) = 'en')
}
"""

OUTPUT_FILE = "data/all_humans/all_human_writing_languages.json"
ERROR_FILE = "data/all_humans/writing_languages_errors.json"
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


def fetch_writing_languages():
    log("[EXTRACTION] Fetching writing languages from QLever...")

    params = {
        "query": QUERY,
        "action": "tsv_export"
    }

    response = requests.get(QLEVER_ENDPOINT, params=params, stream=True)
    response.raise_for_status()

    human_languages = defaultdict(list)
    errors = []
    count = 0

    lines = response.iter_lines(decode_unicode=True)
    header = next(lines)

    for line in tqdm(lines, desc="Parsing writing languages", unit=" rows"):
        if line:
            try:
                parts = line.strip().split("\t")
                if len(parts) >= 3:
                    human_id = extract_qid(parts[0])
                    lang_id = extract_qid(parts[1])
                    lang_label = clean_label(parts[2])
                    human_languages[human_id].append({"id": lang_id, "name": lang_label})
                    count += 1
            except Exception as e:
                errors.append({"line": line, "error": str(e)})

    log(f"[EXTRACTION] Parsed {count:,} writing language assignments for {len(human_languages):,} individuals")

    # Save errors
    if errors:
        log(f"[EXTRACTION] {len(errors)} errors encountered, saving to {ERROR_FILE}")
        with open(ERROR_FILE, "w") as f:
            json.dump(errors, f, indent=2)

        # Retry errors once
        log("[EXTRACTION] Retrying failed rows...")
        retry_count = 0
        for err in errors:
            try:
                parts = err["line"].strip().split("\t")
                if len(parts) >= 3:
                    human_id = extract_qid(parts[0])
                    lang_id = extract_qid(parts[1])
                    lang_label = clean_label(parts[2])
                    human_languages[human_id].append({"id": lang_id, "name": lang_label})
                    retry_count += 1
            except Exception:
                pass
        log(f"[EXTRACTION] Recovered {retry_count} rows on retry")

    # Language distribution
    lang_counts = defaultdict(int)
    for langs in human_languages.values():
        for lang in langs:
            lang_counts[lang["name"]] += 1

    log("\nWriting language distribution (top 20):")
    for lang, cnt in sorted(lang_counts.items(), key=lambda x: -x[1])[:20]:
        log(f"  {lang}: {cnt:,}")

    with open(OUTPUT_FILE, "w") as f:
        json.dump(dict(human_languages), f)

    log(f"[EXTRACTION] Saved writing languages to {OUTPUT_FILE}")
    return human_languages


if __name__ == "__main__":
    fetch_writing_languages()
