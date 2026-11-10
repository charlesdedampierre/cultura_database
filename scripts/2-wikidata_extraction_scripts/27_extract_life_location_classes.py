"""Extract the classes (P31) of every life-location target in targets.json, with
the English label of each class."""
import json
from pathlib import Path

from tqdm import tqdm

from wikidata import clean_literal, extract_qid, values_rows

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "data" / "raw_data_from_wikidata" / "wikidata_extraction_scripts_v2" / "life_locations"

QUERY = """SELECT ?t ?class ?label WHERE {{
  VALUES ?t {{ {values} }}
  ?t wdt:P31 ?class .
  OPTIONAL {{ ?class rdfs:label ?label FILTER(LANG(?label) = "en") }}
}}"""


def main():
    targets = sorted(json.loads((FOLDER / "targets.json").read_text()))
    print(f"{len(targets):,} targets")
    rows, failed = values_rows(targets, QUERY, size=10_000, threads=4, desc="classes")
    classes, labels = {}, {}
    for target, cls, label in tqdm((row + [""] * (3 - len(row)) for row in rows), total=len(rows), desc="parse"):
        classes.setdefault(extract_qid(target), []).append(extract_qid(cls))
        labels[extract_qid(cls)] = labels.get(extract_qid(cls)) or (clean_literal(label) or None)
    (FOLDER / "target_classes.json").write_text(json.dumps({"classes": classes, "labels": labels, "failed_chunks": len(failed)}, ensure_ascii=False))
    print(f"{len(classes):,} targets with a class, {len(labels):,} classes, {len(failed)} failed chunks")


if __name__ == "__main__":
    main()
