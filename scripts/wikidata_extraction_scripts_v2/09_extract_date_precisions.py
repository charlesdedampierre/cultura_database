"""Extract `wikibase:timePrecision` for the date facts of every Q5 human.

Wikidata stores dates with a precision flag (11 = day, 10 = month, 9 = year,
8 = decade, 7 = century, ...). The bare ``wdt:P569`` / ``wdt:P570`` /
``wdt:P1317`` truthy values do not carry the precision; we have to walk
through the statement node to read it.

We pull birth (P569), death (P570), and floruit (P1317) precisions
separately. When a human has multiple precision values for the same field
(rare), we keep the highest (most precise).

Outputs:
    data/all_humans/wikidata_extraction_scripts_v2/date_precisions.json
        {human_qid: {birthdate_precision, deathdate_precision, floruit_precision}}

Run:
    python scripts/wikidata_extraction_scripts_v2/09_extract_date_precisions.py --test
    python scripts/wikidata_extraction_scripts_v2/09_extract_date_precisions.py
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

# (output_key, prop) — same SPARQL pattern just substituting the property.
FIELDS = [
    ("birthdate_precision", "P569"),
    ("deathdate_precision", "P570"),
    ("floruit_precision",   "P1317"),
]

QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX psv: <http://www.wikidata.org/prop/statement/value/>
PREFIX wikibase: <http://wikiba.se/ontology#>

SELECT ?h ?precision WHERE {{
  ?h wdt:P31 wd:Q5 .
  ?h p:{prop} ?stmt .
  ?stmt psv:{prop} ?val .
  ?val wikibase:timePrecision ?precision .
}}{limit}
"""


def fetch_precision(prop: str, limit: int | None, endpoint: str) -> dict[str, int]:
    suffix = f"\nLIMIT {limit}" if limit else ""
    out: dict[str, int] = {}
    for row in tqdm(stream(QUERY.format(prop=prop, limit=suffix), endpoint=endpoint),
                    desc=f"  {prop}", unit=" rows"):
        if len(row) < 2:
            continue
        qid = extract_qid(row[0])
        if not qid.startswith("Q"):
            continue
        token = clean_literal(row[1])
        # WDQS returns plain ints; QLever may return '"11"^^<...>' or similar.
        for cleaner in (token, token.split("^")[0].strip('"')):
            try:
                value = int(float(cleaner))
                break
            except (ValueError, TypeError):
                continue
        else:
            continue
        # keep the most precise value if multiple statements exist
        if qid not in out or value > out[qid]:
            out[qid] = value
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test", action="store_true",
                        help="Run a tiny LIMIT 100 sample.")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    limit = (int(os.environ.get("WIKIDATA_TEST_LIMIT", "100")) if args.test else None)
    endpoint = "wdqs" if args.test else "qlever"
    out_file = OUT_DIR / ("date_precisions.test.json" if args.test else "date_precisions.json")

    print(f"[09] extracting date precisions ({'TEST' if args.test else 'FULL'} mode, endpoint={endpoint})")

    per_field: dict[str, dict[str, int]] = {}
    for key, prop in FIELDS:
        print(f"\n[09] {key} ({prop})")
        per_field[key] = fetch_precision(prop, limit, endpoint)
        print(f"     {len(per_field[key]):,} humans")

    qids = set().union(*per_field.values())
    merged: dict[str, dict[str, int | None]] = {}
    for qid in qids:
        row = {key: per_field[key].get(qid) for key, _ in FIELDS}
        row["id"] = qid
        merged[qid] = row

    with out_file.open("w") as f:
        json.dump(merged, f, ensure_ascii=False)
    print(f"\n[09] saved {out_file} ({len(merged):,} humans with at least one precision)")

    print("\n[09] sample:")
    for qid, row in list(merged.items())[:5]:
        print(f"  {qid}: {row}")


if __name__ == "__main__":
    main()
