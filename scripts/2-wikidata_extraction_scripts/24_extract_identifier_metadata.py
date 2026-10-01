"""Extract the database, country, inception, record count and website of every external-id property."""
import json
from pathlib import Path

import ijson

from wikidata import extract_qid, number, time_value, values_rows

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw_data_from_wikidata"
PROPERTIES = RAW / "all_external_id_properties.json"
OUT = RAW / "wikidata_extraction_scripts_v2" / "identifier_metadata.json"

QUERIES = {
    "issuer": "SELECT ?item ?v WHERE {{ VALUES ?item {{ {values} }} ?item wdt:P1629 ?v }}",
    "country": "SELECT ?item ?v WHERE {{ VALUES ?item {{ {values} }} ?item wdt:P17 ?v }}",
    "website": "SELECT ?item ?v WHERE {{ VALUES ?item {{ {values} }} ?item wdt:P856 ?v }}",
    "number_of_records": "SELECT ?item ?v WHERE {{ VALUES ?item {{ {values} }} ?item wdt:P4876 ?v }}",
    "inception": """SELECT ?item ?v ?precision WHERE {{ VALUES ?item {{ {values} }}
        ?item p:P571 ?s . ?s psv:P571 ?value . ?value wikibase:timeValue ?v ; wikibase:timePrecision ?precision }}""",
}


def read(field, row):
    if field in ("issuer", "country"):
        return extract_qid(row[1])
    if field == "website":
        return row[1].strip("<>")
    if field == "number_of_records":
        value = number(row[1])
        return int(value) if value is not None else None
    return {"date": time_value(row[1]), "precision": int(number(row[2]) or 0)}


ISSUER_FIELDS = ("inception", "website", "number_of_records")


def collect(found, field, rows, owner_of):
    for row in rows:
        for pid in owner_of(extract_qid(row[0])):
            value = read(field, row)
            if value is None:
                continue
            if field == "number_of_records":
                found[pid][field] = max(value, found[pid].get(field) or 0)
            else:
                found[pid].setdefault(field, value)


def main():
    with PROPERTIES.open("rb") as handle:
        pids = sorted({p["property_id"] for p in ijson.items(handle, "properties.item")})
    print(f"{len(pids):,} external-id properties")
    found = {pid: {} for pid in pids}
    for field, query in QUERIES.items():
        rows, failed = values_rows(pids, query, size=2_000, desc=field)
        if failed:
            raise SystemExit(f"{field}: {len(failed)} chunks failed twice")
        collect(found, field, rows, lambda pid: (pid,))
        print(f"   {field}: {sum(1 for v in found.values() if field in v):,} properties")

    by_issuer = {}
    for pid, meta in found.items():
        if "issuer" in meta:
            by_issuer.setdefault(meta["issuer"], []).append(pid)
    for field in ISSUER_FIELDS:
        lacking = {pid for pid, meta in found.items() if field not in meta}
        rows, failed = values_rows(sorted(by_issuer), QUERIES[field], size=2_000, desc=f"issuer {field}")
        if failed:
            raise SystemExit(f"issuer {field}: {len(failed)} chunks failed twice")
        collect(found, field, rows, lambda issuer: [pid for pid in by_issuer.get(issuer, ()) if pid in lacking])
        for pid in lacking:
            if field in found[pid]:
                found[pid].setdefault("read_from_issuer", []).append(field)
        print(f"   {field} with the issuer's: {sum(1 for v in found.values() if field in v):,} properties")
    OUT.write_text(json.dumps(found, ensure_ascii=False, indent=1))
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()
