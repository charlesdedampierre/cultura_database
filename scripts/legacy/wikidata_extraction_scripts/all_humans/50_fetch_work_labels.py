"""
Fetch English labels for every unique work QID found by 49_fetch_all_human_works.

Uses the same per-property pattern as the works extraction so we only ask QLever
for labels of items that are actually authored/created by a human.

Output:
  data/all_humans/work_labels.json   {work_qid: "English label"}
"""

import json
import os
import time
import requests
from tqdm import tqdm

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"

OUTPUT_DIR = "data/all_humans"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "work_labels.json")

PROPS = ["P50", "P170", "P86", "P57", "P162", "P98", "P175", "P110", "P58"]

QUERY_TEMPLATE = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?work ?label WHERE {
  ?human wdt:P31 wd:Q5 .
  ?work wdt:%s ?human .
  ?work rdfs:label ?label .
  FILTER(LANG(?label) = 'en')
}
"""


def extract_qid(uri: str) -> str:
    if "/Q" in uri:
        return uri.split("/")[-1].rstrip(">")
    return uri.strip("<>")


def clean_label(label: str) -> str:
    return label.replace("@en", "").strip().strip('"')


DONE_FLAG = os.path.join(OUTPUT_DIR, "work_labels.done.json")


def load_state():
    if os.path.exists(OUTPUT_FILE):
        print(f"Resuming from existing {OUTPUT_FILE}...")
        with open(OUTPUT_FILE) as f:
            labels = json.load(f)
    else:
        labels = {}
    if os.path.exists(DONE_FLAG):
        with open(DONE_FLAG) as f:
            done = set(json.load(f))
    else:
        done = set()
    print(f"  loaded {len(labels):,} labels, {len(done)} props done: {sorted(done)}")
    return labels, done


def save_state(labels: dict, done: set):
    tmp = OUTPUT_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(labels, f)
    os.replace(tmp, OUTPUT_FILE)
    with open(DONE_FLAG, "w") as f:
        json.dump(sorted(done), f)


def fetch_labels_for(prop: str, labels: dict) -> int:
    query = QUERY_TEMPLATE % prop
    params = {"query": query, "action": "tsv_export"}

    backoff = 10
    response = None
    for attempt in range(8):
        try:
            response = requests.get(QLEVER_ENDPOINT, params=params, stream=True, timeout=120)
        except requests.exceptions.RequestException as e:
            print(f"  network error on {prop}: {e}, retry in {backoff}s...")
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)
            continue
        if response.status_code in (429, 500, 502, 503, 504):
            print(f"  {response.status_code} on {prop}, retry in {backoff}s...")
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)
            continue
        response.raise_for_status()
        break
    else:
        raise RuntimeError(f"giving up on {prop} after retries")

    n = 0
    lines = response.iter_lines(decode_unicode=True)
    next(lines)  # header
    for line in tqdm(lines, desc=f"  {prop}", unit=" rows"):
        if not line:
            continue
        parts = line.strip().split("\t")
        if len(parts) < 2:
            continue
        qid = extract_qid(parts[0])
        if qid in labels:
            continue
        labels[qid] = clean_label(parts[1])
        n += 1
    return n


def fetch_all_labels():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    labels, done = load_state()

    for prop in PROPS:
        if prop in done:
            print(f"\n[{prop}] already done, skipping")
            continue
        print(f"\n[{prop}] fetching labels...")
        added = fetch_labels_for(prop, labels)
        done.add(prop)
        save_state(labels, done)
        print(f"[{prop}] +{added:,} new labels (total {len(labels):,}) — saved")
        time.sleep(3)

    print(f"\nTotal unique work labels: {len(labels):,}")
    save_state(labels, done)
    print(f"Saved {OUTPUT_FILE}")


if __name__ == "__main__":
    fetch_all_labels()
