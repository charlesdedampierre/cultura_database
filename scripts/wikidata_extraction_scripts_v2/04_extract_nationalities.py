"""Extract country of citizenship (P27) for every Q5 human, plus English
labels for each unique nationality QID.

Outputs:
    data/all_humans/nationalities.json         {human_qid: [country_qid, ...]}
    data/all_humans/nationality_labels.json    {country_qid: "label"}

Run:
    python wikidata_extraction_scripts_v2/04_extract_nationalities.py --test
    python wikidata_extraction_scripts_v2/04_extract_nationalities.py
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wikidata import clean_literal, extract_qid, stream  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "all_humans" / "wikidata_extraction_scripts_v2"

NAT_QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?h ?nat WHERE {{
  ?h wdt:P31 wd:Q5 .
  ?h wdt:P27 ?nat .
}}{limit}
"""

LABEL_QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?nat ?label WHERE {{
  ?h wdt:P31 wd:Q5 .
  ?h wdt:P27 ?nat .
  ?nat rdfs:label ?label .
  FILTER(LANG(?label) = 'en')
}}{limit}
"""


def fetch_nationalities(limit: int | None, endpoint: str) -> dict[str, list[str]]:
    suffix = f"\nLIMIT {limit}" if limit else ""
    out: dict[str, list[str]] = defaultdict(list)
    for row in tqdm(stream(NAT_QUERY.format(limit=suffix), endpoint=endpoint),
                    desc="  P27", unit=" rows"):
        if len(row) < 2:
            continue
        qid = extract_qid(row[0])
        nat = extract_qid(row[1])
        if qid.startswith("Q") and nat.startswith("Q"):
            out[qid].append(nat)
    return dict(out)


def fetch_labels(limit: int | None, endpoint: str) -> dict[str, str]:
    suffix = f"\nLIMIT {limit}" if limit else ""
    out: dict[str, str] = {}
    for row in tqdm(stream(LABEL_QUERY.format(limit=suffix), endpoint=endpoint),
                    desc="  labels", unit=" rows"):
        if len(row) < 2:
            continue
        nat = extract_qid(row[0])
        label = clean_literal(row[1])
        if nat.startswith("Q") and label and nat not in out:
            out[nat] = label
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test", action="store_true",
                        help="Run a tiny LIMIT 100 sample.")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    limit = 100 if args.test else None
    endpoint = "wdqs" if args.test else "qlever"
    suffix = ".test" if args.test else ""

    print(f"[04] extracting nationalities ({'TEST' if args.test else 'FULL'} mode, endpoint={endpoint})")

    print("\n[04] human -> nationalities")
    nats = fetch_nationalities(limit, endpoint)
    print(f"     {len(nats):,} humans, "
          f"{sum(len(v) for v in nats.values()):,} (human, nationality) pairs")

    print("\n[04] nationality labels")
    labels = fetch_labels(limit, endpoint)
    print(f"     {len(labels):,} unique nationalities with English labels")

    nat_file = OUT_DIR / f"nationalities{suffix}.json"
    lab_file = OUT_DIR / f"nationality_labels{suffix}.json"
    with nat_file.open("w") as f:
        json.dump(nats, f, ensure_ascii=False)
    with lab_file.open("w") as f:
        json.dump(labels, f, ensure_ascii=False)
    print(f"\n[04] saved {nat_file}")
    print(f"[04] saved {lab_file}")

    print("\n[04] sample:")
    for qid, nat_list in list(nats.items())[:5]:
        named = [f"{n} ({labels.get(n, '?')})" for n in nat_list]
        print(f"  {qid}: {named}")


if __name__ == "__main__":
    main()
