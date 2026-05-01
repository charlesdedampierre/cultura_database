"""Extract birthplace (P19) and deathplace (P20) for every Q5 human.

The values are place QIDs — resolving them to city / country labels and
coordinates is done by downstream enrichment scripts.

Outputs:
    data/all_humans/places.json
    data/all_humans/places.test.json

Run:
    python wikidata_extraction_scripts_v2/02_extract_places.py --test
    python wikidata_extraction_scripts_v2/02_extract_places.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wikidata import extract_qid, stream  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "all_humans" / "wikidata_extraction_scripts_v2"

QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?h ?v WHERE {{
  ?h wdt:P31 wd:Q5 .
  ?h wdt:{prop} ?v .
}}{limit}
"""


def fetch(prop: str, limit: int | None, endpoint: str) -> dict[str, str]:
    suffix = f"\nLIMIT {limit}" if limit else ""
    out: dict[str, str] = {}
    for row in tqdm(stream(QUERY.format(prop=prop, limit=suffix), endpoint=endpoint),
                    desc=f"  {prop}", unit=" rows"):
        if len(row) < 2:
            continue
        qid = extract_qid(row[0])
        place = extract_qid(row[1])
        if qid.startswith("Q") and place.startswith("Q"):
            out[qid] = place
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test", action="store_true",
                        help="Run a tiny LIMIT 100 sample.")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    limit = 100 if args.test else None
    endpoint = "wdqs" if args.test else "qlever"
    out_file = OUT_DIR / ("places.test.json" if args.test else "places.json")

    print(f"[02] extracting places ({'TEST' if args.test else 'FULL'} mode, endpoint={endpoint})")

    print("\n[02] field: birthplace (P19)")
    birth = fetch("P19", limit, endpoint)
    print(f"     {len(birth):,} humans")

    print("\n[02] field: deathplace (P20)")
    death = fetch("P20", limit, endpoint)
    print(f"     {len(death):,} humans")

    merged: dict[str, dict] = {}
    for qid, place in birth.items():
        merged.setdefault(qid, {"id": qid})["birthplace"] = place
    for qid, place in death.items():
        merged.setdefault(qid, {"id": qid})["deathplace"] = place

    with out_file.open("w") as f:
        json.dump(merged, f, ensure_ascii=False)
    print(f"\n[02] saved {out_file} ({len(merged):,} humans)")

    print("\n[02] sample:")
    for qid, row in list(merged.items())[:5]:
        print(f"  {qid}: {row}")


if __name__ == "__main__":
    main()
