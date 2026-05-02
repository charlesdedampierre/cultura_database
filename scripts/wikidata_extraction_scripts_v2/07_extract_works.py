"""Extract every work (book / film / composition / ...) authored or created
by a Q5 human, plus English labels for each unique work QID.

Properties (work --prop--> human):
    P50  author          P57  director          P98  editor
    P170 creator         P162 producer          P175 performer
    P86  composer        P58  screenwriter      P110 illustrator

Outputs:
    data/all_humans/works.json         {human_qid: [{"work": Q..., "prop": P...}, ...]}
    data/all_humans/work_labels.json   {work_qid: "English label"}

Run:
    python wikidata_extraction_scripts_v2/07_extract_works.py --test
    python wikidata_extraction_scripts_v2/07_extract_works.py
"""
from __future__ import annotations

import os
import pathlib

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wikidata import clean_literal, extract_qid, stream  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = pathlib.Path(os.environ["WIKIDATA_OUT_DIR"]) if os.environ.get("WIKIDATA_OUT_DIR") else ROOT / "data" / "all_humans" / "wikidata_extraction_scripts_v2"

PROPS = ["P50", "P170", "P86", "P57", "P162", "P98", "P175", "P110", "P58"]

WORK_QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?h ?work WHERE {{
  ?h wdt:P31 wd:Q5 .
  ?work wdt:{prop} ?h .
}}{limit}
"""

LABEL_QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?work ?label WHERE {{
  ?h wdt:P31 wd:Q5 .
  ?work wdt:{prop} ?h .
  ?work rdfs:label ?label .
  FILTER(LANG(?label) = 'en')
}}{limit}
"""


def fetch_works_for(prop: str, works: dict[str, list[dict]],
                    limit: int | None, endpoint: str) -> int:
    suffix = f"\nLIMIT {limit}" if limit else ""
    n = 0
    for row in tqdm(stream(WORK_QUERY.format(prop=prop, limit=suffix), endpoint=endpoint),
                    desc=f"  {prop}", unit=" rows"):
        if len(row) < 2:
            continue
        h = extract_qid(row[0])
        w = extract_qid(row[1])
        if h.startswith("Q") and w.startswith("Q"):
            works[h].append({"work": w, "prop": prop})
            n += 1
    return n


def fetch_labels_for(prop: str, labels: dict[str, str],
                     limit: int | None, endpoint: str) -> int:
    suffix = f"\nLIMIT {limit}" if limit else ""
    n = 0
    for row in tqdm(stream(LABEL_QUERY.format(prop=prop, limit=suffix), endpoint=endpoint),
                    desc=f"  {prop} labels", unit=" rows"):
        if len(row) < 2:
            continue
        w = extract_qid(row[0])
        label = clean_literal(row[1])
        if w.startswith("Q") and label and w not in labels:
            labels[w] = label
            n += 1
    return n


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test", action="store_true",
                        help="Tiny mode: only P50 (author), LIMIT 100.")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    limit = (int(os.environ.get("WIKIDATA_TEST_LIMIT", "100")) if args.test else None)
    endpoint = "wdqs" if args.test else "qlever"
    suffix = ".test" if args.test else ""
    props = ["P50"] if args.test else PROPS

    print(f"[07] extracting works ({'TEST' if args.test else 'FULL'} mode, endpoint={endpoint})")

    works: dict[str, list[dict]] = defaultdict(list)
    counts: dict[str, int] = {}
    for prop in props:
        print(f"\n[07] works for {prop}")
        counts[prop] = fetch_works_for(prop, works, limit, endpoint)
        print(f"     {counts[prop]:,} new pairs")
        if not args.test:
            time.sleep(2)  # be gentle with QLever

    labels: dict[str, str] = {}
    for prop in props:
        print(f"\n[07] labels for {prop}")
        added = fetch_labels_for(prop, labels, limit, endpoint)
        print(f"     +{added:,} new labels (total {len(labels):,})")
        if not args.test:
            time.sleep(2)

    works_file = OUT_DIR / f"works{suffix}.json"
    labels_file = OUT_DIR / f"work_labels{suffix}.json"
    with works_file.open("w") as f:
        json.dump(dict(works), f, ensure_ascii=False)
    with labels_file.open("w") as f:
        json.dump(labels, f, ensure_ascii=False)

    print(f"\n[07] saved {works_file} ({len(works):,} humans, "
          f"{sum(counts.values()):,} (human, work) pairs)")
    print(f"[07] saved {labels_file} ({len(labels):,} unique work labels)")

    print("\n[07] sample:")
    for qid, items in list(works.items())[:5]:
        named = [f"{i['work']} ({labels.get(i['work'], '?')}) via {i['prop']}"
                 for i in items[:3]]
        more = "" if len(items) <= 3 else f"  …+{len(items)-3} more"
        print(f"  {qid}: {named}{more}")


if __name__ == "__main__":
    main()
