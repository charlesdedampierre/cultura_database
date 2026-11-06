"""Which of Cultura's statements about the CBDB sample are themselves sourced from CBDB?

For every individual in cbdb_sample.json, reads from the Wikidata API the references of the
statements Cultura can build on — date of birth, death, floruit, place of birth, death, country of
citizenship — and marks each statement 'cbdb' when a reference is stated in CBDB, carries a CBDB
id (P497) or a CBDB URL; 'other reference' when it has any other reference; 'no reference'
otherwise. Saved to scripts/5-annotations/data/cbdb_wikidata_references.json so the validation can
leave CBDB-sourced individuals out.

Usage: .venv/bin/python scripts/5-annotations/building_scripts/cbdb_wikidata_references.py
"""

import json
import time
from pathlib import Path

import requests
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[3]
SAMPLE = ROOT / "scripts" / "5-annotations" / "cbdb_validation" / "cbdb_sample.json"
OUT = ROOT / "scripts" / "5-annotations" / "data" / "cbdb_wikidata_references.json"
API = "https://www.wikidata.org/w/api.php"
HEADERS = {"User-Agent": "cultura-database research (cdedampierre@bunka.ai)"}
BATCH = 50

PROPERTIES = {"P569": "date_of_birth", "P570": "date_of_death", "P1317": "floruit", "P19": "place_of_birth", "P20": "place_of_death", "P27": "country_of_citizenship"}
CBDB_NAMES = ("china biographical database", "中國歷代人物傳記", "中国历代人物传记")
RANK = {"no reference": 0, "other reference": 1, "cbdb": 2}


def wikidata(params):
    for attempt in range(5):
        response = requests.get(API, params={**params, "format": "json"}, headers=HEADERS, timeout=120)
        if response.status_code != 429:
            response.raise_for_status()
            return response.json()
        time.sleep(10 * (attempt + 1))
    response.raise_for_status()


def claims(qids):
    found = {}
    for start in tqdm(range(0, len(qids), BATCH), desc="individuals", unit=" batches of 50"):
        found.update(wikidata({"action": "wbgetentities", "ids": "|".join(qids[start:start + BATCH]), "props": "claims"})["entities"])
    return found


def labels(qids):
    names = {}
    for start in range(0, len(qids), BATCH):
        for qid, entity in wikidata({"action": "wbgetentities", "ids": "|".join(qids[start:start + BATCH]), "props": "labels", "languages": "en|zh"})["entities"].items():
            label = entity.get("labels", {})
            names[qid] = " ".join(value["value"] for value in label.values())
    return names


def reference(snaks):
    return {
        "stated_in": [snak["datavalue"]["value"]["id"] for snak in snaks.get("P248", []) if "datavalue" in snak],
        "url": " ".join(snak["datavalue"]["value"] for snak in snaks.get("P854", []) if "datavalue" in snak),
        "cbdb_id": "P497" in snaks,
        "properties": sorted(snaks),
    }


def status_of(ref):
    names = " ".join(ref["stated_in_labels"]).lower()
    if any(name in names for name in CBDB_NAMES) or "cbdb" in ref["url"].lower() or ref["cbdb_id"]:
        return "cbdb"
    return "other reference"


def main():
    qids = [row["qid"] for row in json.loads(SAMPLE.read_text(encoding="utf-8"))]
    print(f"{len(qids)} individuals in {SAMPLE.name}")
    entities = claims(qids)

    statements = []
    for qid, entity in entities.items():
        for pid, name in PROPERTIES.items():
            for claim in entity.get("claims", {}).get(pid, []):
                refs = [reference(r.get("snaks", {})) for r in claim.get("references") or []]
                statements.append({"qid": qid, "pid": pid, "property": name, "references": refs})

    sources = sorted({source for statement in statements for ref in statement["references"] for source in ref["stated_in"]})
    names = labels(sources)
    for statement in statements:
        for ref in statement["references"]:
            ref["stated_in_labels"] = [names.get(source, "") for source in ref["stated_in"]]
        statement["status"] = max((status_of(ref) for ref in statement["references"]), key=RANK.get, default="no reference")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(statements, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(statements)} statements saved to {OUT.relative_to(ROOT)}")
    for name in PROPERTIES.values():
        found = [s["status"] for s in statements if s["property"] == name]
        print(f"   {name:24} {len(found):4}: cbdb {found.count('cbdb'):4} | other reference {found.count('other reference'):4} | none {found.count('no reference'):4}")


if __name__ == "__main__":
    main()
