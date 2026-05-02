"""For every external-ID property already extracted by 06_extract_catalogs,
fetch the metadata used to enrich the ``identifier_types`` table:

    - English label
    - English description
    - issuer (P126 maintained by, OR P137 operator) + label + P31 instance
    - country (P17) + label
    - inception (P571)
    - database records (P4876)
    - official website (P856)
    - formatter URL (P1630, used to build canonical URLs from the raw value)

Mirrors legacy scripts 22 (metadata) and 33 (names).

Output:
    data/all_humans/wikidata_extraction_scripts_v2/catalog_metadata.json
    {
      "P214": {
        "property_id": "P214",
        "label": "VIAF ID",
        "description": "...",
        "issuer_id": "Q54919",
        "issuer_name": "OCLC",
        "issuer_instance": "library cooperative",
        "country_id": "Q30",
        "country_name": "United States of America",
        "inception": "2003",
        "database_records": "...",
        "website": "https://viaf.org/",
        "formatter_url": "https://viaf.org/viaf/$1/"
      }, ...
    }

Run:
    python scripts/wikidata_extraction_scripts_v2/14_extract_catalog_metadata.py --test
    python scripts/wikidata_extraction_scripts_v2/14_extract_catalog_metadata.py
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wikidata import wdqs_json  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = pathlib.Path(os.environ["WIKIDATA_OUT_DIR"]) if os.environ.get("WIKIDATA_OUT_DIR") else ROOT / "data" / "all_humans" / "wikidata_extraction_scripts_v2"

# WDQS handles batch property metadata queries fine; QLever has historically
# been less reliable for property-as-subject queries. We always use WDQS here.
BATCH = 100


METADATA_QUERY = """
SELECT ?prop ?propLabel ?propDescription
       ?issuer ?issuerLabel ?issuerInstanceLabel
       ?country ?countryLabel
       ?inception ?databaseRecords ?website ?formatter
WHERE {{
  VALUES ?prop {{ {values} }}
  OPTIONAL {{ ?prop rdfs:label ?propLabel . FILTER(LANG(?propLabel) = 'en') }}
  OPTIONAL {{ ?prop schema:description ?propDescription . FILTER(LANG(?propDescription) = 'en') }}
  OPTIONAL {{
    {{ ?prop wdt:P126 ?issuer }} UNION {{ ?prop wdt:P137 ?issuer }}
    OPTIONAL {{ ?issuer rdfs:label ?issuerLabel . FILTER(LANG(?issuerLabel) = 'en') }}
    OPTIONAL {{
      ?issuer wdt:P31 ?issuerInstance .
      ?issuerInstance rdfs:label ?issuerInstanceLabel .
      FILTER(LANG(?issuerInstanceLabel) = 'en')
    }}
  }}
  OPTIONAL {{
    ?prop wdt:P17 ?country .
    OPTIONAL {{ ?country rdfs:label ?countryLabel . FILTER(LANG(?countryLabel) = 'en') }}
  }}
  OPTIONAL {{ ?prop wdt:P571 ?inception . }}
  OPTIONAL {{ ?prop wdt:P4876 ?databaseRecords . }}
  OPTIONAL {{ ?prop wdt:P856 ?website . }}
  OPTIONAL {{ ?prop wdt:P1630 ?formatter . }}
}}
"""


def load_property_ids(test: bool) -> list[str]:
    """Pull the list from the v2 catalog_properties.json that 06 produces.
    In --test mode, fall back to a few well-known IDs so this script is
    runnable on its own."""
    if test:
        return ["P214", "P227", "P213", "P244", "P268"]
    f = OUT_DIR / "catalog_properties.json"
    if not f.exists():
        raise FileNotFoundError(
            f"{f} not found — run 06_extract_catalogs.py first "
            f"(or pass --test for a small sample)"
        )
    data = json.loads(f.read_text())
    return [p["property_id"] for p in data["properties"]]


def fetch_batch(pids: list[str]) -> dict[str, dict]:
    values = " ".join(f"wd:{p}" for p in pids)
    data = wdqs_json(METADATA_QUERY.format(values=values), timeout=120)
    out: dict[str, dict] = {}
    for binding in data.get("results", {}).get("bindings", []):
        pid = binding["prop"]["value"].rsplit("/", 1)[-1]
        row = out.setdefault(pid, {"property_id": pid})
        for src, dst in [
            ("propLabel", "label"),
            ("propDescription", "description"),
            ("issuerLabel", "issuer_name"),
            ("issuerInstanceLabel", "issuer_instance"),
            ("countryLabel", "country_name"),
            ("inception", "inception"),
            ("databaseRecords", "database_records"),
            ("website", "website"),
            ("formatter", "formatter_url"),
        ]:
            v = binding.get(src, {}).get("value")
            if v and dst not in row:
                row[dst] = v[:10] if dst == "inception" and len(v) > 10 else v
        for src, dst in [("issuer", "issuer_id"), ("country", "country_id")]:
            v = binding.get(src, {}).get("value", "")
            if v and dst not in row and "/Q" in v:
                row[dst] = v.rsplit("/", 1)[-1]
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test", action="store_true",
                        help="Use 5 well-known property IDs instead of the full list.")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / ("catalog_metadata.test.json" if args.test
                          else "catalog_metadata.json")

    print(f"[14] extracting catalog metadata ({'TEST' if args.test else 'FULL'} mode)")

    pids = load_property_ids(args.test)
    print(f"[14] {len(pids):,} properties to enrich")

    batches = [pids[i:i + BATCH] for i in range(0, len(pids), BATCH)]
    print(f"[14] {len(batches)} batches of up to {BATCH}")

    out: dict[str, dict] = {}
    if args.test:
        for batch in tqdm(batches, desc="  fetching"):
            out.update(fetch_batch(batch))
    else:
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(fetch_batch, b): b for b in batches}
            for f in tqdm(as_completed(futs), total=len(futs), desc="  fetching"):
                out.update(f.result())
                time.sleep(0.05)

    with out_file.open("w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\n[14] saved {out_file} ({len(out):,} properties enriched)")

    print("\n[14] sample:")
    for pid, row in list(out.items())[:5]:
        print(f"  {pid}: {row}")


if __name__ == "__main__":
    main()
