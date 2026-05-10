"""For every occupation QID that appears as a P106 of any Q5 human, fetch
metadata to consolidate the ``occupations`` table downstream:

    - English description
    - instance_of (P31, all values)
    - subclass_of (P279, all *direct* parents — used to root the
      meta-occupation hierarchy locally)

Mirrors the union of legacy scripts 19 (sub-occupations of scientists/
artists) and 25 (occupation descriptions/instance_of).

Output:
    data/all_humans/wikidata_extraction_scripts_v2/occupation_metadata.json
    {
      "Q36180": {
        "id": "Q36180",
        "description": "person who uses written words to communicate ideas",
        "instance_of": ["Q28640"],
        "subclass_of": ["Q482980"]
      }, ...
    }

Run:
    python scripts/wikidata_extraction_scripts_v2/12_extract_occupation_metadata.py --test
    python scripts/wikidata_extraction_scripts_v2/12_extract_occupation_metadata.py
"""
from __future__ import annotations

import os
import pathlib

import argparse
import json
import sys
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wikidata import clean_literal, extract_qid, stream  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = pathlib.Path(os.environ["WIKIDATA_OUT_DIR"]) if os.environ.get("WIKIDATA_OUT_DIR") else ROOT / "data" / "all_humans" / "wikidata_extraction_scripts_v2"

SCOPE = """  ?h wdt:P31 wd:Q5 .
  ?h wdt:P106 ?occ ."""

DESC_QUERY = f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX schema: <http://schema.org/>

SELECT ?occ ?description WHERE {{
{SCOPE}
  ?occ schema:description ?description .
  FILTER(LANG(?description) = 'en')
}}
"""

INSTANCE_QUERY = f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?occ ?instance WHERE {{
{SCOPE}
  ?occ wdt:P31 ?instance .
}}
"""

SUBCLASS_QUERY = f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?occ ?parent WHERE {{
{SCOPE}
  ?occ wdt:P279 ?parent .
}}
"""


def run(query: str, desc: str, limit: int | None, endpoint: str):
    suffix = f"\nLIMIT {limit}" if limit else ""
    return tqdm(stream(query + suffix, endpoint=endpoint),
                desc=f"  {desc}", unit=" rows")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test", action="store_true",
                        help="Run a tiny LIMIT 100 sample.")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    limit = (int(os.environ.get("WIKIDATA_TEST_LIMIT", "100")) if args.test else None)
    endpoint = "wdqs" if args.test else "qlever"
    out_file = OUT_DIR / ("occupation_metadata.test.json" if args.test
                          else "occupation_metadata.json")

    print(f"[12] extracting occupation metadata ({'TEST' if args.test else 'FULL'} mode, endpoint={endpoint})")

    out: dict[str, dict] = {}

    print("\n[12] descriptions")
    for row in run(DESC_QUERY, "schema:description", limit, endpoint):
        if len(row) < 2:
            continue
        qid = extract_qid(row[0])
        desc = clean_literal(row[1])
        if qid.startswith("Q") and desc:
            out.setdefault(qid, {"id": qid}).setdefault("description", desc)

    print("\n[12] instance_of (P31)")
    for row in run(INSTANCE_QUERY, "P31", limit, endpoint):
        if len(row) < 2:
            continue
        qid = extract_qid(row[0])
        inst = extract_qid(row[1])
        if qid.startswith("Q") and inst.startswith("Q"):
            instances = out.setdefault(qid, {"id": qid}).setdefault("instance_of", [])
            if inst not in instances:
                instances.append(inst)

    print("\n[12] subclass_of (P279)")
    for row in run(SUBCLASS_QUERY, "P279", limit, endpoint):
        if len(row) < 2:
            continue
        qid = extract_qid(row[0])
        parent = extract_qid(row[1])
        if qid.startswith("Q") and parent.startswith("Q"):
            parents = out.setdefault(qid, {"id": qid}).setdefault("subclass_of", [])
            if parent not in parents:
                parents.append(parent)

    with out_file.open("w") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"\n[12] saved {out_file} ({len(out):,} unique occupations)")

    print("\n[12] sample:")
    for qid, row in list(out.items())[:5]:
        print(f"  {qid}: {row}")


if __name__ == "__main__":
    main()
