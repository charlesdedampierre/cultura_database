"""Inception (P571) and dissolution (P576) of every Cliopatria polity that names a Wikidata item.

Output: data/raw_data_from_wikidata/wikidata_extraction_scripts_v2/polity_existence.json
    {qid: {"inception": {"date": ISO, "precision": int} | None, "dissolution": {...} | None}}
"""
import json
from pathlib import Path

import ijson

from wikidata import extract_qid, number, time_value, values_rows

ROOT = Path(__file__).resolve().parents[2]
POLITIES = ROOT / "data" / "cliopatria_data" / "cliopatria_V2" / "cliopatria_polities_only_v3.geojson"
OUT = ROOT / "data" / "raw_data_from_wikidata" / "wikidata_extraction_scripts_v2" / "polity_existence.json"

QUERY = """SELECT ?item ?date ?precision WHERE {{
  VALUES ?item {{ {values} }}
  ?item p:{prop} ?statement .
  ?statement psv:{prop} ?value .
  ?value wikibase:timeValue ?date ; wikibase:timePrecision ?precision .
}}"""

PROPERTIES = {"P571": "inception", "P576": "dissolution"}


def polity_qids():
    with POLITIES.open("rb") as handle:
        found = {(feature["properties"].get("Wikidata") or "").strip() for feature in ijson.items(handle, "features.item")}
    return sorted(q for q in found if q.startswith("Q"))


def most_precise(rows):
    best = {}
    for item, date, precision in rows:
        qid, candidate = extract_qid(item), {"date": time_value(date), "precision": int(number(precision) or 0)}
        previous = best.get(qid)
        if previous is None or (candidate["precision"], previous["date"]) > (previous["precision"], candidate["date"]):
            best[qid] = candidate
    return best


def main():
    qids = polity_qids()
    print(f"{len(qids):,} polities with a Wikidata item")
    found = {}
    for prop, name in PROPERTIES.items():
        rows, failed = values_rows(qids, QUERY.replace("{prop}", prop), size=500, desc=name)
        if failed:
            raise SystemExit(f"{name}: {len(failed)} chunks failed twice")
        found[name] = most_precise(rows)
        print(f"   {name}: {len(found[name]):,} polities dated")
    result = {qid: {name: found[name].get(qid) for name in PROPERTIES.values()} for qid in qids}
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()
