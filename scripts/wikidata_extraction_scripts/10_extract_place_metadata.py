"""For every place QID that appears as a birthplace (P19) or deathplace
(P20) of a Q5 human, fetch enough metadata to consolidate the ``cities``
table downstream:

    - English label (rdfs:label)
    - Coordinates (P625)
    - Country (P17)
    - Entity type(s) (P31, all values — used to decide if the place is
      a city/town/village/etc.)
    - English Wikipedia URL

We restrict the queries to places that are actually used as birth/death
places of humans, which keeps the query scope manageable on QLever and
matches the legacy pipeline (scripts 17, 24, 35).

Output:
    data/all_humans/wikidata_extraction_scripts_v2/place_metadata.json
    {
      "Q90": {
        "id": "Q90",
        "label": "Paris",
        "lat": 48.8566, "lon": 2.3522,
        "country": "Q142",
        "entity_types": ["Q515", "Q200250", ...],
        "en_wikipedia_url": "https://en.wikipedia.org/wiki/Paris"
      },
      ...
    }

Run:
    python scripts/wikidata_extraction_scripts_v2/10_extract_place_metadata.py --test
    python scripts/wikidata_extraction_scripts_v2/10_extract_place_metadata.py
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

# Places used as birth or death places of humans. Two queries (one per
# property), then unioned by QID.
PLACE_QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?place ?label WHERE {{
  ?h wdt:P31 wd:Q5 .
  ?h wdt:{prop} ?place .
  OPTIONAL {{ ?place rdfs:label ?label . FILTER(LANG(?label) = 'en') }}
}}{limit}
"""

COORDS_QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?place ?coords WHERE {{
  ?h wdt:P31 wd:Q5 .
  {{ ?h wdt:P19 ?place }} UNION {{ ?h wdt:P20 ?place }}
  ?place wdt:P625 ?coords .
}}{limit}
"""

COUNTRY_QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?place ?country WHERE {{
  ?h wdt:P31 wd:Q5 .
  {{ ?h wdt:P19 ?place }} UNION {{ ?h wdt:P20 ?place }}
  ?place wdt:P17 ?country .
}}{limit}
"""

TYPE_QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?place ?type WHERE {{
  ?h wdt:P31 wd:Q5 .
  {{ ?h wdt:P19 ?place }} UNION {{ ?h wdt:P20 ?place }}
  ?place wdt:P31 ?type .
}}{limit}
"""

SITELINK_QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX schema: <http://schema.org/>

SELECT ?place ?article WHERE {{
  ?h wdt:P31 wd:Q5 .
  {{ ?h wdt:P19 ?place }} UNION {{ ?h wdt:P20 ?place }}
  ?article schema:about ?place .
  ?article schema:isPartOf <https://en.wikipedia.org/> .
}}{limit}
"""


COORD_RE = re.compile(r"^Point\s*\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)$")


def parse_coords(token: str) -> tuple[float, float] | None:
    """Parse 'Point(lon lat)' into (lat, lon). Returns None if unparseable."""
    token = token.strip().strip('"').strip("<>")
    m = COORD_RE.match(token)
    if not m:
        return None
    lon, lat = float(m.group(1)), float(m.group(2))
    return lat, lon


def fetch_pairs(query: str, limit: int | None, endpoint: str,
                desc: str) -> list[tuple[str, str]]:
    suffix = f"\nLIMIT {limit}" if limit else ""
    out: list[tuple[str, str]] = []
    for row in tqdm(stream(query.format(limit=suffix, prop="P19"), endpoint=endpoint)
                    if "{prop}" in query else
                    stream(query.format(limit=suffix), endpoint=endpoint),
                    desc=f"  {desc}", unit=" rows"):
        if len(row) < 2:
            continue
        out.append((row[0], row[1]))
    return out


def fetch_label_pairs(prop: str, limit: int | None, endpoint: str
                      ) -> list[tuple[str, str]]:
    suffix = f"\nLIMIT {limit}" if limit else ""
    out: list[tuple[str, str]] = []
    for row in tqdm(stream(PLACE_QUERY.format(prop=prop, limit=suffix),
                           endpoint=endpoint),
                    desc=f"  labels {prop}", unit=" rows"):
        if not row:
            continue
        place = row[0]
        label = row[1] if len(row) > 1 else ""
        out.append((place, label))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test", action="store_true",
                        help="Run a tiny LIMIT 100 sample.")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    limit = (int(os.environ.get("WIKIDATA_TEST_LIMIT", "100")) if args.test else None)
    endpoint = "wdqs" if args.test else "qlever"
    out_file = OUT_DIR / ("place_metadata.test.json" if args.test
                          else "place_metadata.json")

    print(f"[10] extracting place metadata ({'TEST' if args.test else 'FULL'} mode, endpoint={endpoint})")

    out: dict[str, dict] = {}

    for prop in ("P19", "P20"):
        print(f"\n[10] labels for places used as {prop}")
        for place_uri, label in fetch_label_pairs(prop, limit, endpoint):
            qid = extract_qid(place_uri)
            if not qid.startswith("Q"):
                continue
            row = out.setdefault(qid, {"id": qid})
            label = clean_literal(label)
            if label and "label" not in row:
                row["label"] = label

    print("\n[10] coordinates (P625)")
    for row in tqdm(stream(COORDS_QUERY.format(limit=f"\nLIMIT {limit}" if limit else ""),
                           endpoint=endpoint),
                    desc="  P625", unit=" rows"):
        if len(row) < 2:
            continue
        qid = extract_qid(row[0])
        if not qid.startswith("Q"):
            continue
        coords = parse_coords(row[1])
        if coords is None:
            continue
        place_row = out.setdefault(qid, {"id": qid})
        place_row.setdefault("lat", coords[0])
        place_row.setdefault("lon", coords[1])

    print("\n[10] country (P17)")
    for row in tqdm(stream(COUNTRY_QUERY.format(limit=f"\nLIMIT {limit}" if limit else ""),
                           endpoint=endpoint),
                    desc="  P17", unit=" rows"):
        if len(row) < 2:
            continue
        qid = extract_qid(row[0])
        country = extract_qid(row[1])
        if qid.startswith("Q") and country.startswith("Q"):
            out.setdefault(qid, {"id": qid}).setdefault("country", country)

    print("\n[10] entity types (P31)")
    for row in tqdm(stream(TYPE_QUERY.format(limit=f"\nLIMIT {limit}" if limit else ""),
                           endpoint=endpoint),
                    desc="  P31", unit=" rows"):
        if len(row) < 2:
            continue
        qid = extract_qid(row[0])
        type_qid = extract_qid(row[1])
        if qid.startswith("Q") and type_qid.startswith("Q"):
            place_row = out.setdefault(qid, {"id": qid})
            types = place_row.setdefault("entity_types", [])
            if type_qid not in types:
                types.append(type_qid)

    print("\n[10] English Wikipedia URLs")
    for row in tqdm(stream(SITELINK_QUERY.format(limit=f"\nLIMIT {limit}" if limit else ""),
                           endpoint=endpoint),
                    desc="  enwiki", unit=" rows"):
        if len(row) < 2:
            continue
        qid = extract_qid(row[0])
        url = row[1].strip().strip("<>")
        if qid.startswith("Q") and url:
            out.setdefault(qid, {"id": qid}).setdefault("en_wikipedia_url", url)

    with out_file.open("w") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"\n[10] saved {out_file} ({len(out):,} unique places)")

    print("\n[10] sample:")
    for qid, row in list(out.items())[:5]:
        print(f"  {qid}: {row}")


if __name__ == "__main__":
    main()
