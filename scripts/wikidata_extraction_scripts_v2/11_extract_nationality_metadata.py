"""For every nationality QID that appears as a P27 (country of citizenship)
of any Q5 human, fetch metadata to consolidate the ``nationalities`` table
downstream:

    - English label, English description
    - instance_of (P31, all values — used to detect "country", "former
      country", "kingdom", etc.)
    - country (P17 — for sub-national or historical entities)
    - replaced_by (P1366 — chain to the modern successor state)
    - capital (P36 — used to fall back to coordinates via the capital city)
    - coordinates (P625 — direct or via capital P36 → P625)
    - English Wikipedia URL

Mirrors the union of legacy scripts 18, 23, 29, 30.

Output:
    data/all_humans/wikidata_extraction_scripts_v2/nationality_metadata.json
    {
      "Q142": {
        "id": "Q142",
        "label": "France",
        "description": "country in Western Europe",
        "instance_of": ["Q3624078", "Q6256"],
        "country": "Q142",
        "replaced_by": [],
        "capital": "Q90",
        "lat": 46.0, "lon": 2.0,
        "en_wikipedia_url": "https://en.wikipedia.org/wiki/France"
      }, ...
    }

Run:
    python scripts/wikidata_extraction_scripts_v2/11_extract_nationality_metadata.py --test
    python scripts/wikidata_extraction_scripts_v2/11_extract_nationality_metadata.py
"""
from __future__ import annotations

import os
import pathlib

import argparse
import json
import re
import sys
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wikidata import clean_literal, extract_qid, stream  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = pathlib.Path(os.environ["WIKIDATA_OUT_DIR"]) if os.environ.get("WIKIDATA_OUT_DIR") else ROOT / "data" / "all_humans" / "wikidata_extraction_scripts_v2"

# All queries are scoped to "things actually used as P27 of a Q5".
SCOPE = """  ?h wdt:P31 wd:Q5 .
  ?h wdt:P27 ?nat ."""

LABEL_QUERY = f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX schema: <http://schema.org/>

SELECT ?nat ?label ?description WHERE {{
{SCOPE}
  OPTIONAL {{ ?nat rdfs:label ?label . FILTER(LANG(?label) = 'en') }}
  OPTIONAL {{ ?nat schema:description ?description . FILTER(LANG(?description) = 'en') }}
}}
"""

INSTANCE_QUERY = f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?nat ?instance WHERE {{
{SCOPE}
  ?nat wdt:P31 ?instance .
}}
"""

COUNTRY_QUERY = f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?nat ?country WHERE {{
{SCOPE}
  ?nat wdt:P17 ?country .
}}
"""

REPLACED_QUERY = f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?nat ?successor WHERE {{
{SCOPE}
  ?nat wdt:P1366 ?successor .
}}
"""

CAPITAL_QUERY = f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?nat ?capital WHERE {{
{SCOPE}
  ?nat wdt:P36 ?capital .
}}
"""

COORDS_QUERY = f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?nat ?coords WHERE {{
{SCOPE}
  ?nat wdt:P625 ?coords .
}}
"""

CAPITAL_COORDS_QUERY = f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?nat ?coords WHERE {{
{SCOPE}
  ?nat wdt:P36 ?capital .
  ?capital wdt:P625 ?coords .
}}
"""

SITELINK_QUERY = f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX schema: <http://schema.org/>

SELECT ?nat ?article WHERE {{
{SCOPE}
  ?article schema:about ?nat .
  ?article schema:isPartOf <https://en.wikipedia.org/> .
}}
"""

COORD_RE = re.compile(r"^Point\s*\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)$")


def parse_coords(token: str) -> tuple[float, float] | None:
    token = token.strip().strip('"').strip("<>")
    m = COORD_RE.match(token)
    if not m:
        return None
    lon, lat = float(m.group(1)), float(m.group(2))
    return lat, lon


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
    out_file = OUT_DIR / ("nationality_metadata.test.json" if args.test
                          else "nationality_metadata.json")

    print(f"[11] extracting nationality metadata ({'TEST' if args.test else 'FULL'} mode, endpoint={endpoint})")

    out: dict[str, dict] = {}

    print("\n[11] labels + descriptions")
    for row in run(LABEL_QUERY, "label/desc", limit, endpoint):
        if not row:
            continue
        qid = extract_qid(row[0])
        if not qid.startswith("Q"):
            continue
        place = out.setdefault(qid, {"id": qid})
        if len(row) > 1 and row[1]:
            label = clean_literal(row[1])
            if label:
                place.setdefault("label", label)
        if len(row) > 2 and row[2]:
            desc = clean_literal(row[2])
            if desc:
                place.setdefault("description", desc)

    print("\n[11] instance_of (P31)")
    for row in run(INSTANCE_QUERY, "P31", limit, endpoint):
        if len(row) < 2:
            continue
        qid = extract_qid(row[0])
        inst = extract_qid(row[1])
        if qid.startswith("Q") and inst.startswith("Q"):
            instances = out.setdefault(qid, {"id": qid}).setdefault("instance_of", [])
            if inst not in instances:
                instances.append(inst)

    print("\n[11] country (P17)")
    for row in run(COUNTRY_QUERY, "P17", limit, endpoint):
        if len(row) < 2:
            continue
        qid = extract_qid(row[0])
        country = extract_qid(row[1])
        if qid.startswith("Q") and country.startswith("Q"):
            out.setdefault(qid, {"id": qid}).setdefault("country", country)

    print("\n[11] replaced_by (P1366)")
    for row in run(REPLACED_QUERY, "P1366", limit, endpoint):
        if len(row) < 2:
            continue
        qid = extract_qid(row[0])
        succ = extract_qid(row[1])
        if qid.startswith("Q") and succ.startswith("Q"):
            chain = out.setdefault(qid, {"id": qid}).setdefault("replaced_by", [])
            if succ not in chain:
                chain.append(succ)

    print("\n[11] capital (P36)")
    for row in run(CAPITAL_QUERY, "P36", limit, endpoint):
        if len(row) < 2:
            continue
        qid = extract_qid(row[0])
        cap = extract_qid(row[1])
        if qid.startswith("Q") and cap.startswith("Q"):
            out.setdefault(qid, {"id": qid}).setdefault("capital", cap)

    print("\n[11] coordinates (P625, direct)")
    for row in run(COORDS_QUERY, "P625", limit, endpoint):
        if len(row) < 2:
            continue
        qid = extract_qid(row[0])
        coords = parse_coords(row[1])
        if coords is None or not qid.startswith("Q"):
            continue
        place = out.setdefault(qid, {"id": qid})
        place.setdefault("lat", coords[0])
        place.setdefault("lon", coords[1])

    print("\n[11] coordinates (via capital P36 → P625)")
    for row in run(CAPITAL_COORDS_QUERY, "capital→coords", limit, endpoint):
        if len(row) < 2:
            continue
        qid = extract_qid(row[0])
        coords = parse_coords(row[1])
        if coords is None or not qid.startswith("Q"):
            continue
        place = out.setdefault(qid, {"id": qid})
        # only fill if direct P625 didn't already populate
        place.setdefault("lat", coords[0])
        place.setdefault("lon", coords[1])

    print("\n[11] English Wikipedia URLs")
    for row in run(SITELINK_QUERY, "enwiki", limit, endpoint):
        if len(row) < 2:
            continue
        qid = extract_qid(row[0])
        url = row[1].strip().strip("<>")
        if qid.startswith("Q") and url:
            out.setdefault(qid, {"id": qid}).setdefault("en_wikipedia_url", url)

    with out_file.open("w") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"\n[11] saved {out_file} ({len(out):,} unique nationalities)")

    print("\n[11] sample:")
    for qid, row in list(out.items())[:5]:
        print(f"  {qid}: {row}")


if __name__ == "__main__":
    main()
