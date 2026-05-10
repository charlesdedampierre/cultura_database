"""Extract external catalog identifiers (VIAF, GND, ISNI, Library of Congress,
BnF, ...) for every Q5 human.

Two phases:
    1. Get the canonical list of every ``wikibase:ExternalId`` property from
       the official Wikidata SPARQL endpoint (source of truth — QLever's
       property metadata can lag).
    2. For each property, stream all (human, value) pairs from QLever and
       write them as one JSON file per property under
       ``data/all_humans/identifiers_per_property/``. Properties whose JSON
       already exists are skipped, so re-running is a free resume.

Outputs:
    data/all_humans/catalog_properties.json
        the property list with id, label, formatter URL
    data/all_humans/identifiers_per_property/<Pxxx>.json
        {pid, n_pairs, pairs: [[human_qid, value], ...]}
    data/all_humans/catalogs.json
        flat map {human_qid: {Pxxx: [value, ...]}}

Run:
    python wikidata_extraction_scripts_v2/06_extract_catalogs.py --test
    python wikidata_extraction_scripts_v2/06_extract_catalogs.py
"""
from __future__ import annotations

import os
import pathlib

import argparse
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wikidata import extract_qid, stream, wdqs_json  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = pathlib.Path(os.environ["WIKIDATA_OUT_DIR"]) if os.environ.get("WIKIDATA_OUT_DIR") else ROOT / "data" / "all_humans" / "wikidata_extraction_scripts_v2"
PER_PROP_DIR = OUT_DIR / "identifiers_per_property"

THREADS = 8

PROP_LIST_QUERY = """
SELECT ?prop ?propLabel ?formatterURL WHERE {
  ?prop wikibase:propertyType wikibase:ExternalId .
  OPTIONAL { ?prop wdt:P1630 ?formatterURL . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""

VALUE_QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?h ?v WHERE {{
  ?h wdt:P31 wd:Q5 .
  ?h wdt:{pid} ?v .
}}{limit}
"""


def fetch_property_list() -> list[dict]:
    print("[06] fetching canonical external-ID property list (live WDQS)...")
    data = wdqs_json(PROP_LIST_QUERY)
    rows = data["results"]["bindings"]
    out = []
    for row in rows:
        pid = row["prop"]["value"].rsplit("/", 1)[-1]
        label = row.get("propLabel", {}).get("value", "")
        formatter = row.get("formatterURL", {}).get("value", "")
        out.append({"property_id": pid, "label": label, "formatter_url": formatter})
    out.sort(key=lambda p: int(p["property_id"][1:]))
    return out


def out_path(pid: str) -> Path:
    return PER_PROP_DIR / f"{pid}.json"


def already_done(pid: str) -> bool:
    p = out_path(pid)
    if not p.exists():
        return False
    try:
        return json.loads(p.read_text()).get("error") is None
    except Exception:
        return False


def fetch_values(pid: str, limit: int | None, endpoint: str) -> dict:
    suffix = f"\nLIMIT {limit}" if limit else ""
    pairs: list[list[str]] = []
    try:
        for row in stream(VALUE_QUERY.format(pid=pid, limit=suffix), endpoint=endpoint):
            if len(row) < 2:
                continue
            qid = extract_qid(row[0])
            if not qid.startswith("Q"):
                continue
            value = row[1].strip()
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            elif value.startswith("<") and value.endswith(">"):
                value = value[1:-1]
            pairs.append([qid, value])
        return {"pid": pid, "n_pairs": len(pairs), "pairs": pairs, "error": None}
    except Exception as exc:
        return {"pid": pid, "n_pairs": 0, "pairs": [], "error": f"{type(exc).__name__}: {exc}"}


def process(pid: str, limit: int | None, endpoint: str) -> dict:
    if limit is None and already_done(pid):
        return {"pid": pid, "skipped": True}
    result = fetch_values(pid, limit, endpoint)
    if limit is None:
        out_path(pid).parent.mkdir(parents=True, exist_ok=True)
        out_path(pid).write_text(json.dumps(result, ensure_ascii=False))
    return result


def merge_into_flat(props: list[dict]) -> dict[str, dict[str, list[str]]]:
    """Merge every per-property JSON into a single {human_qid: {Pxxx: [v, ...]}} map."""
    flat: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for p in tqdm(props, desc="  merging"):
        pid = p["property_id"]
        path = out_path(pid)
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        for qid, value in data.get("pairs", []):
            flat[qid][pid].append(value)
    return {q: dict(v) for q, v in flat.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test", action="store_true",
                        help="Tiny mode: only the 3 most common identifier props (P214 VIAF, "
                             "P227 GND, P213 ISNI) with LIMIT 100.")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PER_PROP_DIR.mkdir(parents=True, exist_ok=True)

    endpoint = "wdqs" if args.test else "qlever"
    print(f"[06] extracting catalogs ({'TEST' if args.test else 'FULL'} mode, endpoint={endpoint})")

    if args.test:
        props = [
            {"property_id": "P214", "label": "VIAF ID", "formatter_url": "https://viaf.org/viaf/$1/"},
            {"property_id": "P227", "label": "GND ID", "formatter_url": ""},
            {"property_id": "P213", "label": "ISNI", "formatter_url": ""},
        ]
        limit = int(os.environ.get("WIKIDATA_TEST_LIMIT", "100"))
    else:
        props = fetch_property_list()
        prop_file = OUT_DIR / "catalog_properties.json"
        prop_file.write_text(json.dumps({"n_properties": len(props), "properties": props},
                                        indent=2, ensure_ascii=False))
        print(f"[06] saved {prop_file} ({len(props):,} properties)")
        limit = None

    pending = [p["property_id"] for p in props
               if limit is not None or not already_done(p["property_id"])]
    print(f"[06] {len(pending):,}/{len(props):,} properties to fetch "
          f"(rest already on disk)")

    results: list[dict] = []
    if args.test:
        for pid in pending:
            print(f"\n[06] {pid}")
            r = process(pid, limit, endpoint)
            print(f"     {r['n_pairs']:,} pairs"
                  f"{' (error: ' + r['error'] + ')' if r.get('error') else ''}")
            results.append(r)
    else:
        with ThreadPoolExecutor(max_workers=THREADS) as ex:
            futs = {ex.submit(process, pid, limit, endpoint): pid for pid in pending}
            for f in tqdm(as_completed(futs), total=len(futs), desc="  fetching"):
                results.append(f.result())
                time.sleep(0.05)  # gentle on QLever

    if args.test:
        flat: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for r in results:
            for qid, value in r.get("pairs", []):
                flat[qid][r["pid"]].append(value)
        flat_dict = {q: dict(v) for q, v in flat.items()}
        out_file = OUT_DIR / "catalogs.test.json"
    else:
        flat_dict = merge_into_flat(props)
        out_file = OUT_DIR / "catalogs.json"

    with out_file.open("w") as f:
        json.dump(flat_dict, f, ensure_ascii=False)
    print(f"\n[06] saved {out_file} ({len(flat_dict):,} humans)")

    print("\n[06] sample:")
    for qid, ids in list(flat_dict.items())[:5]:
        print(f"  {qid}: {ids}")


if __name__ == "__main__":
    main()
