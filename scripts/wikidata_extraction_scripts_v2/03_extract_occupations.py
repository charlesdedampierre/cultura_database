"""Extract occupations (P106) for every Q5 human, plus English labels for
each unique occupation QID.

Outputs:
    data/all_humans/occupations.json         {human_qid: [occupation_qid, ...]}
    data/all_humans/occupation_labels.json   {occupation_qid: "label"}

Run:
    python wikidata_extraction_scripts_v2/03_extract_occupations.py --test
    python wikidata_extraction_scripts_v2/03_extract_occupations.py
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

OCC_QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?h ?occ WHERE {{
  ?h wdt:P31 wd:Q5 .
  ?h wdt:P106 ?occ .
}}{limit}
"""

LABEL_QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?occ ?label WHERE {{
  ?h wdt:P31 wd:Q5 .
  ?h wdt:P106 ?occ .
  ?occ rdfs:label ?label .
  FILTER(LANG(?label) = 'en')
}}{limit}
"""


def fetch_occupations(limit: int | None, endpoint: str) -> dict[str, list[str]]:
    suffix = f"\nLIMIT {limit}" if limit else ""
    out: dict[str, list[str]] = defaultdict(list)
    for row in tqdm(stream(OCC_QUERY.format(limit=suffix), endpoint=endpoint),
                    desc="  P106", unit=" rows"):
        if len(row) < 2:
            continue
        qid = extract_qid(row[0])
        occ = extract_qid(row[1])
        if qid.startswith("Q") and occ.startswith("Q"):
            out[qid].append(occ)
    return dict(out)


def fetch_labels(limit: int | None, endpoint: str) -> dict[str, str]:
    suffix = f"\nLIMIT {limit}" if limit else ""
    out: dict[str, str] = {}
    for row in tqdm(stream(LABEL_QUERY.format(limit=suffix), endpoint=endpoint),
                    desc="  labels", unit=" rows"):
        if len(row) < 2:
            continue
        occ = extract_qid(row[0])
        label = clean_literal(row[1])
        if occ.startswith("Q") and label and occ not in out:
            out[occ] = label
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

    print(f"[03] extracting occupations ({'TEST' if args.test else 'FULL'} mode, endpoint={endpoint})")

    print("\n[03] human -> occupations")
    occs = fetch_occupations(limit, endpoint)
    print(f"     {len(occs):,} humans, "
          f"{sum(len(v) for v in occs.values()):,} (human, occupation) pairs")

    print("\n[03] occupation labels")
    labels = fetch_labels(limit, endpoint)
    print(f"     {len(labels):,} unique occupations with English labels")

    occ_file = OUT_DIR / f"occupations{suffix}.json"
    lab_file = OUT_DIR / f"occupation_labels{suffix}.json"
    with occ_file.open("w") as f:
        json.dump(occs, f, ensure_ascii=False)
    with lab_file.open("w") as f:
        json.dump(labels, f, ensure_ascii=False)
    print(f"\n[03] saved {occ_file}")
    print(f"[03] saved {lab_file}")

    print("\n[03] sample:")
    for qid, occ_list in list(occs.items())[:5]:
        named = [f"{o} ({labels.get(o, '?')})" for o in occ_list]
        print(f"  {qid}: {named}")


if __name__ == "__main__":
    main()
