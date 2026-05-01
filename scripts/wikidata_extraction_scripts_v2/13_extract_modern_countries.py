"""Fetch every Wikidata entity that has an ISO 3166-1 alpha-3 code (P298).

This is the universe of "modern countries" used by the cliopatria /
nationalities pipelines to ground every individual to a present-day
sovereign state. We intentionally do NOT scope to "P31 wd:Q6256" because
some dependent territories that get their own ISO3 code are not modeled
as Q6256 in Wikidata.

For each country we collect:
    - English label
    - ISO 3166-1 alpha-3 (P298)
    - continent (P30) + English label
    - capital (P36)
    - English Wikipedia URL

Mirrors legacy script 31 plus the country Wikipedia bit of
``extract_country_wikipedia.py``.

Output:
    data/all_humans/wikidata_extraction_scripts_v2/modern_countries.json
    {
      "Q142": {
        "id": "Q142",
        "name": "France",
        "iso_a3_code": "FRA",
        "continent_id": "Q46",
        "continent": "Europe",
        "capital": "Q90",
        "en_wikipedia_url": "https://en.wikipedia.org/wiki/France"
      }, ...
    }

Run:
    python scripts/wikidata_extraction_scripts_v2/13_extract_modern_countries.py --test
    python scripts/wikidata_extraction_scripts_v2/13_extract_modern_countries.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wikidata import clean_literal, extract_qid, stream  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "all_humans" / "wikidata_extraction_scripts_v2"


COUNTRY_QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?country ?label ?iso3 ?continent ?continentLabel WHERE {{
  ?country wdt:P298 ?iso3 .
  OPTIONAL {{ ?country rdfs:label ?label . FILTER(LANG(?label) = 'en') }}
  OPTIONAL {{
    ?country wdt:P30 ?continent .
    OPTIONAL {{ ?continent rdfs:label ?continentLabel . FILTER(LANG(?continentLabel) = 'en') }}
  }}
}}{limit}
"""

CAPITAL_QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?country ?capital WHERE {{
  ?country wdt:P298 ?iso3 .
  ?country wdt:P36 ?capital .
}}{limit}
"""

SITELINK_QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX schema: <http://schema.org/>

SELECT ?country ?article WHERE {{
  ?country wdt:P298 ?iso3 .
  ?article schema:about ?country .
  ?article schema:isPartOf <https://en.wikipedia.org/> .
}}{limit}
"""


def run(query: str, desc: str, limit: int | None, endpoint: str):
    suffix = f"\nLIMIT {limit}" if limit else ""
    return tqdm(stream(query.format(limit=suffix), endpoint=endpoint),
                desc=f"  {desc}", unit=" rows")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test", action="store_true",
                        help="Run a tiny LIMIT 100 sample.")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    limit = 100 if args.test else None
    endpoint = "wdqs" if args.test else "qlever"
    out_file = OUT_DIR / ("modern_countries.test.json" if args.test
                          else "modern_countries.json")

    print(f"[13] extracting modern countries ({'TEST' if args.test else 'FULL'} mode, endpoint={endpoint})")

    out: dict[str, dict] = {}

    print("\n[13] countries with ISO3, label, continent")
    for row in run(COUNTRY_QUERY, "P298+P30", limit, endpoint):
        if len(row) < 3:
            continue
        qid = extract_qid(row[0])
        if not qid.startswith("Q"):
            continue
        label = clean_literal(row[1]) if row[1] else None
        iso3 = clean_literal(row[2]) if row[2] else None
        if not iso3 or len(iso3) != 3 or not iso3.isalpha():
            continue
        iso3 = iso3.upper()
        continent_id = extract_qid(row[3]) if len(row) > 3 and row[3] else None
        continent_name = clean_literal(row[4]) if len(row) > 4 and row[4] else None
        existing = out.setdefault(qid, {"id": qid})
        existing.setdefault("name", label)
        existing.setdefault("iso_a3_code", iso3)
        if continent_id and "continent_id" not in existing:
            existing["continent_id"] = continent_id
            existing["continent"] = continent_name

    print("\n[13] capitals (P36)")
    for row in run(CAPITAL_QUERY, "P36", limit, endpoint):
        if len(row) < 2:
            continue
        qid = extract_qid(row[0])
        cap = extract_qid(row[1])
        if qid in out and cap.startswith("Q"):
            out[qid].setdefault("capital", cap)

    print("\n[13] English Wikipedia URLs")
    for row in run(SITELINK_QUERY, "enwiki", limit, endpoint):
        if len(row) < 2:
            continue
        qid = extract_qid(row[0])
        url = row[1].strip().strip("<>")
        if qid in out and url:
            out[qid].setdefault("en_wikipedia_url", url)

    with out_file.open("w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\n[13] saved {out_file} ({len(out):,} countries)")

    print("\n[13] sample:")
    for qid, row in list(out.items())[:5]:
        print(f"  {qid}: {row}")


if __name__ == "__main__":
    main()
