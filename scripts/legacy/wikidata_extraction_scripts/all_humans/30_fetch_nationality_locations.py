"""
Fetch geographic locations (coordinates) for nationalities using QLever.
Gets P625 (coordinate location) or P36 (capital) coordinates for nationality entities.
"""

import json
import requests
from tqdm import tqdm
import sqlite3

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"
DB_PATH = "data/humans_clean.sqlite3"
OUTPUT_FILE = "data/all_humans/nationality_locations.json"
ERROR_FILE = "data/all_humans/nationality_locations_errors.json"
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


def fetch_direct_coords_batch(qids: list) -> dict:
    """Fetch direct coordinate locations (P625) for a batch."""
    values = " ".join([f"wd:{qid}" for qid in qids])

    query = f"""
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?entity ?coords WHERE {{
  VALUES ?entity {{ {values} }}
  ?entity wdt:P625 ?coords .
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
                coords = parts[1]
                # Parse POINT(lon lat) format
                if "POINT(" in coords:
                    coord_str = coords.split("POINT(")[1].rstrip(")")
                    lon_str, lat_str = coord_str.split()
                    results[qid] = {"lat": float(lat_str), "lon": float(lon_str)}

    return results


def fetch_capital_coords_batch(qids: list) -> dict:
    """Fetch capital city (P36) coordinates for entities without direct coords."""
    values = " ".join([f"wd:{qid}" for qid in qids])

    query = f"""
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?entity ?coords WHERE {{
  VALUES ?entity {{ {values} }}
  ?entity wdt:P36 ?capital .
  ?capital wdt:P625 ?coords .
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
                coords = parts[1]
                if "POINT(" in coords:
                    coord_str = coords.split("POINT(")[1].rstrip(")")
                    lon_str, lat_str = coord_str.split()
                    if qid not in results:
                        results[qid] = {"lat": float(lat_str), "lon": float(lon_str)}

    return results


def main():
    log("[EXTRACTION] Fetching nationality locations from QLever...")

    nat_ids = get_nationality_ids()
    log(f"[EXTRACTION] Found {len(nat_ids)} nationalities with wikidata_id")

    all_locations = {}
    errors = []
    batch_size = 500

    # Step 1: Direct coordinates
    log("[EXTRACTION] Step 1: Fetching direct coordinates (P625)...")
    for i in tqdm(range(0, len(nat_ids), batch_size), desc="Direct coords"):
        batch = nat_ids[i:i + batch_size]
        try:
            results = fetch_direct_coords_batch(batch)
            all_locations.update(results)
        except Exception as e:
            errors.append({"step": "direct", "batch_start": i, "ids": batch, "error": str(e)})

    log(f"[EXTRACTION] Found direct coordinates for {len(all_locations)} nationalities")

    # Step 2: Capital coordinates for remaining
    remaining = [qid for qid in nat_ids if qid not in all_locations]
    log(f"[EXTRACTION] Step 2: Fetching capital coordinates for {len(remaining)} remaining...")

    for i in tqdm(range(0, len(remaining), batch_size), desc="Capital coords"):
        batch = remaining[i:i + batch_size]
        try:
            results = fetch_capital_coords_batch(batch)
            all_locations.update(results)
        except Exception as e:
            errors.append({"step": "capital", "batch_start": i, "ids": batch, "error": str(e)})

    # Retry errors once
    if errors:
        log(f"[EXTRACTION] Retrying {len(errors)} failed batches...")
        with open(ERROR_FILE, "w") as f:
            json.dump([{"step": e["step"], "batch_start": e["batch_start"], "error": e["error"]} for e in errors], f)

        for err in errors:
            try:
                if err["step"] == "direct":
                    results = fetch_direct_coords_batch(err["ids"])
                else:
                    results = fetch_capital_coords_batch(err["ids"])
                all_locations.update(results)
            except Exception:
                pass

    with open(OUTPUT_FILE, "w") as f:
        json.dump(all_locations, f, indent=2)

    log(f"[EXTRACTION] Saved {len(all_locations)} nationality locations to {OUTPUT_FILE}")
    log(f"[EXTRACTION] Coverage: {len(all_locations)}/{len(nat_ids)} ({100 * len(all_locations) / max(len(nat_ids), 1):.1f}%)")


if __name__ == "__main__":
    main()
