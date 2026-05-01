"""
Fetch Wikidata instance types (P31) + English labels for every id in the
`cities` table of `data/humans_clean.sqlite3` using QLever in bulk.

Output:
- data/all_humans/city_entity_types.json
    { "Q100": {
        "types": [
          {"id": "Q1549591", "label": "big city"},
          {"id": "Q1093829", "label": "city in the United States"}
        ]
      }, ... }
- data/all_humans/city_entity_types_errors.json
    list of failed batches (after 1 retry)

Progress is written to task.log at project root and to stdout via tqdm.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from datetime import datetime

import requests
from tqdm import tqdm

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"
DB_PATH = "data/humans_clean.sqlite3"
OUTPUT_DIR = "data/all_humans"
OUT_FILE = f"{OUTPUT_DIR}/city_entity_types.json"
ERR_FILE = f"{OUTPUT_DIR}/city_entity_types_errors.json"
TASK_LOG = "task.log"

BATCH_SIZE = 500
REQUEST_TIMEOUT = 120
SLEEP_BETWEEN_BATCHES = 0.25
MAX_RETRIES_PER_BATCH = 5
BACKOFF_BASE = 1.5  # seconds; waits 1.5, 3, 6, 12, 24s on successive 429/5xx


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(TASK_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def extract_qid(uri: str) -> str:
    if not uri:
        return ""
    if "/" in uri:
        uri = uri.split("/")[-1]
    return uri.rstrip(">")


def strip_lang_tag(s: str) -> str:
    if s.endswith("@en"):
        s = s[:-3]
    return s.strip('"')


def load_city_ids(db_path: str) -> list[str]:
    log(f"Opening {db_path} to read city ids...")
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT id FROM cities "
            "WHERE id IS NOT NULL AND id != '' AND id LIKE 'Q%'"
        )
        ids = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()
    log(f"Loaded {len(ids):,} distinct city Wikidata ids")
    return ids


def fetch_batch(ids: list[str]) -> dict[str, list[dict]]:
    """Fetch P31 (instance of) for a batch of ids. Returns {qid: [{id,label}...]}.
    Retries internally on 429 / 5xx with exponential backoff.
    Raises only if every retry fails.
    """
    values = " ".join(f"wd:{q}" for q in ids)
    query = f"""
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?item ?type ?typeLabel WHERE {{
  VALUES ?item {{ {values} }}
  ?item wdt:P31 ?type .
  OPTIONAL {{
    ?type rdfs:label ?typeLabel .
    FILTER(LANG(?typeLabel) = "en")
  }}
}}
"""
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES_PER_BATCH):
        try:
            resp = requests.post(
                QLEVER_ENDPOINT,
                data={"query": query, "action": "tsv_export"},
                timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": "CulturaDatabase/1.0"},
            )
            if resp.status_code in (429, 500, 502, 503, 504):
                wait = BACKOFF_BASE * (2**attempt)
                time.sleep(wait)
                last_exc = requests.HTTPError(
                    f"{resp.status_code} {resp.reason} for url: {resp.url}"
                )
                continue
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            last_exc = e
            wait = BACKOFF_BASE * (2**attempt)
            time.sleep(wait)
    else:
        raise last_exc if last_exc else RuntimeError("unknown fetch error")

    out: dict[str, list[dict]] = {}
    seen: dict[str, set[str]] = {}
    lines = resp.text.strip().split("\n")
    for line in lines[1:]:  # skip header
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        qid = extract_qid(parts[0])
        type_id = extract_qid(parts[1])
        label = strip_lang_tag(parts[2]) if len(parts) >= 3 else ""
        if not qid or not type_id:
            continue
        bucket = out.setdefault(qid, [])
        seen_for = seen.setdefault(qid, set())
        if type_id in seen_for:
            continue
        seen_for.add(type_id)
        bucket.append({"id": type_id, "label": label})
    return out


def run_batches(
    batches: list[list[str]], desc: str
) -> tuple[dict[str, list[dict]], list[list[str]]]:
    results: dict[str, list[dict]] = {}
    failed: list[list[str]] = []
    pbar = tqdm(batches, desc=desc, unit="batch")
    for batch in pbar:
        try:
            data = fetch_batch(batch)
            results.update(data)
            pbar.set_postfix({"entities": len(results)})
        except Exception as e:  # noqa: BLE001
            log(f"  batch failed ({len(batch)} ids): {e}")
            failed.append(batch)
        time.sleep(SLEEP_BETWEEN_BATCHES)
    return results, failed


def main() -> int:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    log("=" * 60)
    log("FETCH CITY ENTITY TYPES (P31) FROM QLEVER")
    log("=" * 60)

    db_path = sys.argv[1] if len(sys.argv) > 1 else DB_PATH
    ids = load_city_ids(db_path)

    if not ids:
        log("No ids to fetch, exiting.")
        return 0

    batches = [ids[i : i + BATCH_SIZE] for i in range(0, len(ids), BATCH_SIZE)]
    log(f"Prepared {len(batches)} batches of up to {BATCH_SIZE} ids each")

    # Pass 1
    log("Pass 1/2: fetching all batches...")
    results, failed = run_batches(batches, desc="Fetch P31 (pass 1)")
    log(f"Pass 1 done. entities={len(results):,} failed_batches={len(failed)}")

    # Pass 2 — retry failed once
    if failed:
        log(f"Pass 2/2: retrying {len(failed)} failed batches...")
        retry_results, still_failed = run_batches(failed, desc="Fetch P31 (retry)")
        results.update(retry_results)
        log(
            f"Pass 2 done. entities_total={len(results):,} "
            f"still_failed_batches={len(still_failed)}"
        )
    else:
        still_failed = []

    # Wrap output into per-entity dict
    log(f"Writing {OUT_FILE}...")
    payload = {qid: {"types": types} for qid, types in results.items()}
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    if still_failed:
        log(f"Writing {ERR_FILE} ({len(still_failed)} batches)...")
        with open(ERR_FILE, "w", encoding="utf-8") as f:
            json.dump(still_failed, f, ensure_ascii=False)
    else:
        # remove stale error file if it exists
        if os.path.exists(ERR_FILE):
            os.remove(ERR_FILE)

    covered = len(results)
    missing = len(ids) - covered
    log(f"Coverage: {covered:,}/{len(ids):,} cities have >=1 P31 value")
    log(f"Missing : {missing:,} cities have no P31 returned")
    log("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
