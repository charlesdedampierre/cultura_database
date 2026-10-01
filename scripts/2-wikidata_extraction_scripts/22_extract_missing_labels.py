"""Extract a label for the humans that have no English name."""
import json
from pathlib import Path

import ijson
from tqdm import tqdm

from wikidata import clean_literal, extract_qid, values_rows

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw_data_from_wikidata"
IDS = RAW / "all_human_ids.json"
NAMES = RAW / "all_human_names.json"
OUT = RAW / "wikidata_extraction_scripts_v2" / "missing_labels.json"
ERRORS = ROOT / "logs" / "missing_labels.errors.json"

QUERY = """SELECT ?item ?label WHERE {{
  VALUES ?item {{ {values} }}
  ?item rdfs:label ?label FILTER(LANG(?label) = "LANGUAGE")
}}"""

ANY_LANGUAGE = """SELECT ?item ?label (LANG(?label) AS ?language) WHERE {{
  VALUES ?item {{ {values} }}
  ?item rdfs:label ?label
}} ORDER BY ?item ?language"""


def missing_qids():
    with NAMES.open("rb") as handle:
        named = {qid for qid, _ in tqdm(ijson.kvitems(handle, ""), desc="named", unit=" qids", mininterval=5)}
    with IDS.open("rb") as handle:
        return sorted(qid for qid in ijson.items(handle, "item") if qid not in named)


def main():
    todo = missing_qids()
    print(f"{len(todo):,} humans have no label in {NAMES.name}")
    found, errors = {}, []
    for language in ("en", "mul"):
        rows, failed = values_rows(todo, QUERY.replace("LANGUAGE", language), desc=language)
        errors += [{"language": language, "qids": batch} for batch in failed]
        for item, label in rows:
            found.setdefault(extract_qid(item), {"label": clean_literal(label), "language": language})
        todo = [qid for qid in todo if qid not in found]
        print(f"   {language}: {len(found):,} recovered so far, {len(todo):,} still without a label")
    rows, failed = values_rows(todo, ANY_LANGUAGE, desc="any language")
    errors += [{"language": "any", "qids": batch} for batch in failed]
    for item, label, language in sorted(rows, key=lambda row: (row[0], row[2])):
        found.setdefault(extract_qid(item), {"label": clean_literal(label), "language": clean_literal(language)})
    print(f"   any language: {len(found):,} recovered, {len(todo) - sum(1 for q in todo if q in found):,} have no label at all")
    OUT.write_text(json.dumps(found, ensure_ascii=False))
    ERRORS.parent.mkdir(exist_ok=True)
    ERRORS.write_text(json.dumps(errors))
    print(f"saved {OUT}; {sum(len(e['qids']) for e in errors):,} qids in failed chunks, listed in {ERRORS}")


if __name__ == "__main__":
    main()
