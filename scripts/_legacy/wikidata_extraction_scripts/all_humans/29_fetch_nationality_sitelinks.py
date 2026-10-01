"""
Fetch English Wikipedia sitelinks for all nationalities in the database.
Uses QLever bulk query to get en.wikipedia.org URLs for nationality entities.
"""

import json
import requests
from tqdm import tqdm
import sqlite3

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"
DB_PATH = "data/humans_clean.sqlite3"
OUTPUT_FILE = "data/all_humans/nationality_sitelinks.json"
ERROR_FILE = "data/all_humans/nationality_sitelinks_errors.json"
TASK_LOG = "task.log"


def log(msg):
    with open(TASK_LOG, "a") as f:
        f.write(msg + "\n")
    print(msg)


def extract_qid(uri: str) -> str:
    if "/Q" in uri:
        return uri.split("/")[-1].rstrip(">")
    return uri


def get_nationality_ids():
    """Get all nationality wikidata_ids from the database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT wikidata_id FROM nationalities WHERE wikidata_id IS NOT NULL AND wikidata_id != ''")
    ids = [r[0] for r in c.fetchall()]
    conn.close()
    return ids


def fetch_sitelinks_batch(qids: list) -> dict:
    """Fetch English Wikipedia sitelinks for a batch of QIDs."""
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
    response = requests.post(QLEVER_ENDPOINT, data=data)
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
    log("[EXTRACTION] Fetching English Wikipedia sitelinks for nationalities...")

    nat_ids = get_nationality_ids()
    log(f"[EXTRACTION] Found {len(nat_ids)} nationalities with wikidata_id")

    all_sitelinks = {}
    errors = []
    batch_size = 500

    for i in tqdm(range(0, len(nat_ids), batch_size), desc="Fetching nationality sitelinks"):
        batch = nat_ids[i:i + batch_size]
        try:
            results = fetch_sitelinks_batch(batch)
            all_sitelinks.update(results)
        except Exception as e:
            errors.append({"batch_start": i, "ids": batch, "error": str(e)})
            log(f"[EXTRACTION] Error in batch {i}: {e}")

    # Retry errors once
    if errors:
        log(f"[EXTRACTION] Retrying {len(errors)} failed batches...")
        with open(ERROR_FILE, "w") as f:
            json.dump([{"batch_start": e["batch_start"], "error": e["error"]} for e in errors], f)

        retry_errors = []
        for err in errors:
            try:
                results = fetch_sitelinks_batch(err["ids"])
                all_sitelinks.update(results)
            except Exception as e:
                retry_errors.append({"batch_start": err["batch_start"], "error": str(e)})

        if retry_errors:
            log(f"[EXTRACTION] {len(retry_errors)} batches still failed after retry")
            with open(ERROR_FILE, "w") as f:
                json.dump(retry_errors, f)
        else:
            log("[EXTRACTION] All retries succeeded")

    with open(OUTPUT_FILE, "w") as f:
        json.dump(all_sitelinks, f, indent=2, ensure_ascii=False)

    log(f"[EXTRACTION] Saved {len(all_sitelinks)} nationality sitelinks to {OUTPUT_FILE}")
    log(f"[EXTRACTION] Coverage: {len(all_sitelinks)}/{len(nat_ids)} ({100 * len(all_sitelinks) / max(len(nat_ids), 1):.1f}%)")


if __name__ == "__main__":
    main()
