"""Extract core per-human facts from Wikidata.

For every Q5 (human) we collect:
    - name (English label)
    - description (English)
    - gender (P21)
    - birthdate (P569)
    - deathdate (P570)
    - floruit (P1317)

Each fact is fetched with its own QLever query (one column = fast streaming
TSV), then merged into a single dict keyed by human QID.

Outputs:
    data/all_humans/main_info.json        full extraction
    data/all_humans/main_info.test.json   --test mode, 100 humans

Run:
    python wikidata_extraction_scripts_v2/01_extract_main_info.py --test
    python wikidata_extraction_scripts_v2/01_extract_main_info.py
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wikidata import clean_literal, extract_qid, stream  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = pathlib.Path(os.environ["WIKIDATA_OUT_DIR"]) if os.environ.get("WIKIDATA_OUT_DIR") else ROOT / "data" / "all_humans" / "wikidata_extraction_scripts_v2"

# (key, sparql snippet, takes_label_filter)
FIELDS = [
    ("name",        "?h rdfs:label ?v . FILTER(LANG(?v) = 'en')"),
    ("description", "?h schema:description ?v . FILTER(LANG(?v) = 'en')"),
    ("gender",      "?h wdt:P21 ?v ."),
    ("birthdate",   "?h wdt:P569 ?v ."),
    ("deathdate",   "?h wdt:P570 ?v ."),
    ("floruit",     "?h wdt:P1317 ?v ."),
]

QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX schema: <http://schema.org/>

SELECT ?h ?v WHERE {{
  ?h wdt:P31 wd:Q5 .
  {body}
}}{limit}
"""


def fetch_field(field: str, body: str, limit: int | None, endpoint: str) -> dict[str, str]:
    """Return {human_qid: value} for one field. Last value wins on duplicates,
    which matches the existing behaviour of the legacy scripts."""
    suffix = f"\nLIMIT {limit}" if limit else ""
    query = QUERY.format(body=body, limit=suffix)

    out: dict[str, str] = {}
    for row in tqdm(stream(query, endpoint=endpoint), desc=f"  {field}", unit=" rows"):
        if len(row) < 2:
            continue
        qid = extract_qid(row[0])
        if not qid.startswith("Q"):
            continue
        value = row[1]
        # gender values are QID URIs; normalize to QID. Other values are
        # literals — strip quotes and lang tag.
        if "wikidata.org/entity/" in value or value.startswith("<"):
            value = extract_qid(value)
        else:
            value = clean_literal(value)
        out[qid] = value
    return out


def merge(per_field: dict[str, dict[str, str]]) -> dict[str, dict]:
    """Pivot {field: {qid: v}} into {qid: {field: v}}. Adds qid as ``id``."""
    merged: dict[str, dict] = {}
    for field, values in per_field.items():
        for qid, v in values.items():
            row = merged.setdefault(qid, {"id": qid})
            row[field] = v
    return merged


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test", action="store_true",
                        help="Run a tiny LIMIT 100 sample to validate the script.")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    limit = (int(os.environ.get("WIKIDATA_TEST_LIMIT", "100")) if args.test else None)
    endpoint = "wdqs" if args.test else "qlever"
    out_file = OUT_DIR / ("main_info.test.json" if args.test else "main_info.json")

    print(f"[01] extracting main info ({'TEST' if args.test else 'FULL'} mode, endpoint={endpoint})")
    per_field = {}
    for field, body in FIELDS:
        print(f"\n[01] field: {field}")
        per_field[field] = fetch_field(field, body, limit, endpoint)
        print(f"     {len(per_field[field]):,} rows")

    merged = merge(per_field)
    print(f"\n[01] merged into {len(merged):,} unique humans")

    with out_file.open("w") as f:
        json.dump(merged, f, ensure_ascii=False)
    print(f"[01] saved {out_file}")

    print("\n[01] sample:")
    for qid, row in list(merged.items())[:5]:
        print(f"  {qid}: {row}")


if __name__ == "__main__":
    main()
