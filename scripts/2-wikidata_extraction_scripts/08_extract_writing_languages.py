"""Extract writing language (P6886) for every Q5 human, plus English labels
for each unique language QID.

Outputs:
    data/all_humans/wikidata_extraction_scripts_v2/writing_languages.json
        {human_qid: [language_qid, ...]}
    data/all_humans/wikidata_extraction_scripts_v2/writing_language_labels.json
        {language_qid: "English label"}

Run:
    python scripts/wikidata_extraction_scripts_v2/08_extract_writing_languages.py --test
    python scripts/wikidata_extraction_scripts_v2/08_extract_writing_languages.py
"""
from __future__ import annotations

import os
import pathlib

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wikidata import clean_literal, extract_qid, stream  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = pathlib.Path(os.environ["WIKIDATA_OUT_DIR"]) if os.environ.get("WIKIDATA_OUT_DIR") else ROOT / "data" / "all_humans" / "wikidata_extraction_scripts_v2"

LANG_QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?h ?lang WHERE {{
  ?h wdt:P31 wd:Q5 .
  ?h wdt:P6886 ?lang .
}}{limit}
"""

LABEL_QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?lang ?label WHERE {{
  ?h wdt:P31 wd:Q5 .
  ?h wdt:P6886 ?lang .
  ?lang rdfs:label ?label .
  FILTER(LANG(?label) = 'en')
}}{limit}
"""


def fetch_pairs(limit: int | None, endpoint: str) -> dict[str, list[str]]:
    suffix = f"\nLIMIT {limit}" if limit else ""
    out: dict[str, list[str]] = defaultdict(list)
    for row in tqdm(stream(LANG_QUERY.format(limit=suffix), endpoint=endpoint),
                    desc="  P6886", unit=" rows"):
        if len(row) < 2:
            continue
        qid = extract_qid(row[0])
        lang = extract_qid(row[1])
        if qid.startswith("Q") and lang.startswith("Q"):
            out[qid].append(lang)
    return dict(out)


def fetch_labels(limit: int | None, endpoint: str) -> dict[str, str]:
    suffix = f"\nLIMIT {limit}" if limit else ""
    out: dict[str, str] = {}
    for row in tqdm(stream(LABEL_QUERY.format(limit=suffix), endpoint=endpoint),
                    desc="  labels", unit=" rows"):
        if len(row) < 2:
            continue
        lang = extract_qid(row[0])
        label = clean_literal(row[1])
        if lang.startswith("Q") and label and lang not in out:
            out[lang] = label
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test", action="store_true",
                        help="Run a tiny LIMIT 100 sample.")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    limit = (int(os.environ.get("WIKIDATA_TEST_LIMIT", "100")) if args.test else None)
    endpoint = "wdqs" if args.test else "qlever"
    suffix = ".test" if args.test else ""

    print(f"[08] extracting writing languages ({'TEST' if args.test else 'FULL'} mode, endpoint={endpoint})")

    print("\n[08] human -> writing languages")
    langs = fetch_pairs(limit, endpoint)
    print(f"     {len(langs):,} humans, "
          f"{sum(len(v) for v in langs.values()):,} (human, language) pairs")

    print("\n[08] language labels")
    labels = fetch_labels(limit, endpoint)
    print(f"     {len(labels):,} unique writing languages with English labels")

    langs_file = OUT_DIR / f"writing_languages{suffix}.json"
    labels_file = OUT_DIR / f"writing_language_labels{suffix}.json"
    with langs_file.open("w") as f:
        json.dump(langs, f, ensure_ascii=False)
    with labels_file.open("w") as f:
        json.dump(labels, f, ensure_ascii=False)

    print(f"\n[08] saved {langs_file}")
    print(f"[08] saved {labels_file}")

    print("\n[08] sample:")
    for qid, lang_list in list(langs.items())[:5]:
        named = [f"{l} ({labels.get(l, '?')})" for l in lang_list]
        print(f"  {qid}: {named}")


if __name__ == "__main__":
    main()
