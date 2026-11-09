"""Extract the Wikidata classes (P31) of every external-id property, used to tell identifiers of people apart from account handles and identifiers of works, places or organizations."""
import json
from pathlib import Path

import ijson

from wikidata import extract_qid, values_rows

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw_data_from_wikidata"
PROPERTIES = RAW / "all_external_id_properties.json"
OUT = RAW / "wikidata_extraction_scripts_v2" / "identifier_property_types.json"

QUERY = "SELECT ?item ?v WHERE {{ VALUES ?item {{ {values} }} ?item wdt:P31 ?v }}"


def main():
    with PROPERTIES.open("rb") as handle:
        pids = sorted({p["property_id"] for p in ijson.items(handle, "properties.item")})
    print(f"{len(pids):,} external-id properties")
    rows, failed = values_rows(pids, QUERY, size=2_000, desc="P31")
    if failed:
        raise SystemExit(f"{len(failed)} chunks failed twice")
    classes = {pid: [] for pid in pids}
    for row in rows:
        classes[extract_qid(row[0])].append(extract_qid(row[1]))
    OUT.write_text(json.dumps({pid: sorted(set(found)) for pid, found in classes.items()}, indent=1))
    print(f"{sum(1 for found in classes.values() if found):,} properties with a class -> {OUT}")


if __name__ == "__main__":
    main()
