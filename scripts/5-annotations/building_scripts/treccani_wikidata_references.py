"""Which of Cultura's statements about the Treccani sample are themselves sourced from Treccani?

For every individual in the Treccani AI annotations, reads from the Wikidata API the references
of the statements Cultura can build on — date of birth, death, floruit, place of birth, death,
country of citizenship — and marks each statement 'treccani' when a reference is stated in a
Treccani work, carries a Treccani id (P1986) or a treccani.it URL; 'other reference' when it has
any other reference; 'no reference' otherwise. Saved to annotations/data/treccani_wikidata_references.json
so the validation can leave Treccani-sourced statements out.

Usage: .venv/bin/python annotations/building_scripts/treccani_wikidata_references.py
"""

import json
import time
from pathlib import Path

import pyarrow.parquet as pq
import requests
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
ANNOTATIONS = ROOT / "annotations" / "treccani_validation" / "treccani_ai_annotations_cultura289.parquet"
OUT = ROOT / "annotations" / "data" / "treccani_wikidata_references.json"
API = "https://www.wikidata.org/w/api.php"
HEADERS = {"User-Agent": "cultura-database research (cdedampierre@bunka.ai)"}
BATCH = 50

PROPERTIES = {"P569": "date_of_birth", "P570": "date_of_death", "P1317": "floruit", "P19": "place_of_birth", "P20": "place_of_death", "P27": "country_of_citizenship"}
TRECCANI_NAMES = ("dizionario biografico", "treccani", "enciclopedia italiana", "enciclopedia dei papi", "enciclopedia dantesca", "federiciana")
RANK = {"no reference": 0, "other reference": 1, "treccani": 2}


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
        for qid, entity in wikidata({"action": "wbgetentities", "ids": "|".join(qids[start:start + BATCH]), "props": "labels", "languages": "en|it"})["entities"].items():
            label = entity.get("labels", {})
            names[qid] = (label.get("en") or label.get("it") or {}).get("value", "")
    return names


def reference(snaks):
    return {
        "stated_in": [snak["datavalue"]["value"]["id"] for snak in snaks.get("P248", []) if "datavalue" in snak],
        "url": " ".join(snak["datavalue"]["value"] for snak in snaks.get("P854", []) if "datavalue" in snak),
        "treccani_id": "P1986" in snaks,
        "properties": sorted(snaks),
    }


def status_of(ref):
    names = " ".join(ref["stated_in_labels"]).lower()
    if any(name in names for name in TRECCANI_NAMES) or "treccani.it" in ref["url"].lower() or ref["treccani_id"]:
        return "treccani"
    return "other reference"


def main():
    qids = [row["entity"]["qid"] for row in pq.read_table(ANNOTATIONS).to_pylist()]
    print(f"{len(qids)} individuals in {ANNOTATIONS.name}")
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
        print(f"   {name:24} {len(found):4}: treccani {found.count('treccani'):4} | other reference {found.count('other reference'):4} | none {found.count('no reference'):4}")


if __name__ == "__main__":
    main()
