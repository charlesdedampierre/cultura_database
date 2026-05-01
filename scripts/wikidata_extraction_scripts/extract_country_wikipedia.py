"""
Fetch English Wikipedia sitelinks for all distinct country IDs found in place_locations.json.
Uses QLever bulk query. Saves results as JSON in data/all_humans/country_wikipedia_urls.json
"""

import json
import requests
import subprocess
import os

try:
    subprocess.Popen(["caffeinate"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except FileNotFoundError:
    pass

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"
PLACE_LOCATIONS_PATH = "data/all_humans/place_locations.json"
OUTPUT_PATH = "data/all_humans/country_wikipedia_urls.json"
ERROR_PATH = "data/all_humans/country_wikipedia_urls_errors.json"
TASK_LOG = "task.log"


def log(msg):
    print(msg, flush=True)
    with open(TASK_LOG, "a") as f:
        f.write(msg + "\n")


def extract_qid(uri):
    if "/Q" in uri:
        return uri.split("/")[-1].rstrip(">")
    return uri


def fetch_sitelinks_batch(qids):
    values = " ".join([f"wd:{qid}" for qid in qids])
    query = f"""
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX schema: <http://schema.org/>

SELECT ?entity ?article WHERE {{
  VALUES ?entity {{ {values} }}
  ?article schema:about ?entity .
  ?article schema:isPartOf <https://en.wikipedia.org/> .
}}
"""
    data = {"query": query, "action": "tsv_export"}
    response = requests.post(QLEVER_ENDPOINT, data=data, timeout=60)
    response.raise_for_status()

    results = {}
    lines = response.text.strip().split("\n")
    for line in lines[1:]:
        if line:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                qid = extract_qid(parts[0])
                url = parts[1].strip("<>")
                results[qid] = url
    return results


def main():
    log("[Extract] Fetching English Wikipedia URLs for country IDs...")

    # Get all distinct country IDs from place_locations
    with open(PLACE_LOCATIONS_PATH) as f:
        pl = json.load(f)

    country_ids = set()
    country_names = {}
    for v in pl.values():
        cid = v.get("country_id")
        cname = v.get("country_name")
        if cid:
            country_ids.add(cid)
            if cid not in country_names and cname:
                country_names[cid] = cname

    country_ids = sorted(list(country_ids))
    log(f"[Extract] Found {len(country_ids)} distinct country IDs")

    all_sitelinks = {}
    errors = []
    batch_size = 200

    for i in range(0, len(country_ids), batch_size):
        batch = country_ids[i : i + batch_size]
        try:
            results = fetch_sitelinks_batch(batch)
            all_sitelinks.update(results)
            log(
                f"[Extract] Batch {i//batch_size + 1}/{(len(country_ids) + batch_size - 1)//batch_size}: got {len(results)} URLs"
            )
        except Exception as e:
            errors.append({"batch_start": i, "ids": batch, "error": str(e)})
            log(f"[Extract] Error in batch {i}: {e}")

    # Retry errors once
    if errors:
        log(f"[Extract] Retrying {len(errors)} failed batches...")
        retry_errors = []
        for err in errors:
            try:
                results = fetch_sitelinks_batch(err["ids"])
                all_sitelinks.update(results)
            except Exception as e:
                retry_errors.append(
                    {"batch_start": err["batch_start"], "error": str(e)}
                )
        if retry_errors:
            log(f"[Extract] {len(retry_errors)} batches still failed after retry")
            with open(ERROR_PATH, "w") as f:
                json.dump(retry_errors, f)
        else:
            log("[Extract] All retries succeeded")

    # Build final output: country_id -> {name, en_wikipedia_url}
    output = {}
    for cid in country_ids:
        entry = {"country_name": country_names.get(cid, "")}
        if cid in all_sitelinks:
            entry["en_wikipedia_url"] = all_sitelinks[cid]
        output[cid] = entry

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    with_url = sum(1 for v in output.values() if "en_wikipedia_url" in v)
    log(
        f"[Extract] Saved {len(output)} country entries ({with_url} with Wikipedia URL) to {OUTPUT_PATH}"
    )
    log("[Extract] Done.")


if __name__ == "__main__":
    main()
