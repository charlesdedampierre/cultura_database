"""
Fetch all works (books, films, compositions, ...) authored/created by humans
in Wikidata, via QLever bulk SPARQL.

Properties used (work --prop--> human):
  P50  author
  P170 creator
  P86  composer
  P57  director
  P162 producer
  P98  editor
  P175 performer
  P110 illustrator
  P58  screenwriter

Outputs:
  data/all_humans/all_human_works.json   {human_qid: [{"work": Q..., "prop": P...}, ...]}
  data/all_humans/all_human_works.tsv    raw streamed rows (human_qid\twork_qid\tprop)

Estimated runtime: ~5-10 minutes.
"""

import json
import os
import time
import requests
from collections import defaultdict
from tqdm import tqdm

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"

OUTPUT_DIR = "data/all_humans"
OUTPUT_JSON = os.path.join(OUTPUT_DIR, "all_human_works.json")
OUTPUT_TSV = os.path.join(OUTPUT_DIR, "all_human_works.tsv")

PROPS = ["P50", "P170", "P86", "P57", "P162", "P98", "P175", "P110", "P58"]

QUERY_TEMPLATE = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?human ?work WHERE {
  ?human wdt:P31 wd:Q5 .
  ?work wdt:%s ?human .
}
"""


def extract_qid(uri: str) -> str:
    if "/Q" in uri:
        return uri.split("/")[-1].rstrip(">")
    return uri.strip("<>")


def fetch_one_property(prop: str, human_works: dict, tsv) -> int:
    query = QUERY_TEMPLATE % prop
    params = {"query": query, "action": "tsv_export"}

    backoff = 5
    for attempt in range(6):
        response = requests.get(QLEVER_ENDPOINT, params=params, stream=True)
        if response.status_code == 429:
            print(f"  429 on {prop}, retry in {backoff}s...")
            time.sleep(backoff)
            backoff = min(backoff * 2, 120)
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
        human_qid = extract_qid(parts[0])
        work_qid = extract_qid(parts[1])
        human_works[human_qid].append({"work": work_qid, "prop": prop})
        tsv.write(f"{human_qid}\t{work_qid}\t{prop}\n")
        n += 1
    return n


def fetch_all_works():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"Querying QLever for all human works across {len(PROPS)} properties...")

    human_works = defaultdict(list)
    counts = {}

    with open(OUTPUT_TSV, "w") as tsv:
        tsv.write("human_qid\twork_qid\tprop\n")
        for prop in PROPS:
            print(f"\n[{prop}] starting...")
            counts[prop] = fetch_one_property(prop, human_works, tsv)
            tsv.flush()
            print(f"[{prop}] {counts[prop]:,} rows")
            time.sleep(2)  # be gentle with QLever

    total = sum(counts.values())
    print(f"\n=== Summary ===")
    for prop in PROPS:
        print(f"  {prop}: {counts[prop]:>12,}")
    print(f"  Total rows: {total:,}")
    print(f"  Humans with >=1 work: {len(human_works):,}")

    print(f"\nWriting JSON mapping to {OUTPUT_JSON} ...")
    with open(OUTPUT_JSON, "w") as f:
        json.dump(dict(human_works), f)

    print(f"Saved {OUTPUT_JSON}")
    print(f"Saved {OUTPUT_TSV}")
    return human_works


if __name__ == "__main__":
    fetch_all_works()
