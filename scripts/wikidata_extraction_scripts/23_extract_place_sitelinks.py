"""English Wikipedia article of every place (birthplaces, deathplaces), in the same
{qid: url} shape as nationality_sitelinks.json.

Output: data/raw_data_from_wikidata/wikidata_extraction_scripts_v2/place_sitelinks.json
"""
import json
from pathlib import Path

import ijson

from wikidata import extract_qid, values_rows

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw_data_from_wikidata"
PLACE_FILES = (
    RAW / "place_locations.json",
    RAW / "city_entity_types.json",
    RAW / "wikidata_extraction_scripts_v2" / "place_inception.json",
    RAW / "wikidata_extraction_scripts_v2" / "place_dissolution.json",
)
OUT = RAW / "wikidata_extraction_scripts_v2" / "place_sitelinks.json"

QUERY = """SELECT ?item ?article WHERE {{
  VALUES ?item {{ {values} }}
  ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> .
}}"""


def place_qids():
    found = set()
    for path in PLACE_FILES:
        with path.open("rb") as handle:
            found.update(qid for qid, _ in ijson.kvitems(handle, ""))
    return sorted(q for q in found if q.startswith("Q"))


def main():
    qids = place_qids()
    print(f"{len(qids):,} places")
    rows, failed = values_rows(qids, QUERY, desc="places")
    if failed:
        raise SystemExit(f"{len(failed)} chunks failed twice")
    found = {extract_qid(item): article.strip("<>") for item, article in rows}
    OUT.write_text(json.dumps(found, ensure_ascii=False))
    print(f"{len(found):,} places have an English Wikipedia article; saved {OUT}")


if __name__ == "__main__":
    main()
