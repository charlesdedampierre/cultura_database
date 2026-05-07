"""Path A — step 1.

Fetch the canonical list of all `wikibase:ExternalId` properties from the
LIVE Wikidata SPARQL endpoint (source of truth, not QLever which had stale
property metadata in our earlier extraction).

Output: data/all_humans/all_external_id_properties.json
Format: { "properties": [ {"property_id": "P214", "label": "VIAF ID", ... }, ... ] }
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
OUT_FILE = ROOT / "data" / "all_humans" / "all_external_id_properties.json"
TASK_LOG = ROOT / "task.log"
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "identifier_extraction_v2.log"

WDQS = "https://query.wikidata.org/sparql"
HEADERS = {
    "User-Agent": "cultura-database-research/1.0 (cdedampierre@bunka.ai)",
    "Accept": "application/sparql-results+json",
}

QUERY = """
SELECT ?prop ?propLabel ?formatterURL WHERE {
  ?prop wikibase:propertyType wikibase:ExternalId .
  OPTIONAL { ?prop wdt:P1630 ?formatterURL . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""


def log(msg: str) -> None:
    stamped = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(stamped, flush=True)
    LOG_DIR.mkdir(exist_ok=True)
    with TASK_LOG.open("a") as f:
        f.write(stamped + "\n")
    with LOG_FILE.open("a") as f:
        f.write(stamped + "\n")


def main():
    log("[45] Fetching canonical external-ID property list from live Wikidata...")
    t0 = time.time()
    r = requests.get(WDQS, params={"query": QUERY}, headers=HEADERS, timeout=180)
    r.raise_for_status()
    data = r.json()

    rows = data["results"]["bindings"]
    properties = []
    for row in rows:
        pid_uri = row["prop"]["value"]
        pid = pid_uri.rsplit("/", 1)[-1]
        label = row.get("propLabel", {}).get("value", "")
        formatter = row.get("formatterURL", {}).get("value", "")
        properties.append({
            "property_id": pid,
            "label": label,
            "formatter_url": formatter,
        })

    properties.sort(key=lambda p: int(p["property_id"][1:]))

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUT_FILE.open("w") as f:
        json.dump({
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "source": "https://query.wikidata.org/sparql",
            "n_properties": len(properties),
            "properties": properties,
        }, f, indent=2, ensure_ascii=False)

    log(f"[45] Wrote {len(properties):,} properties to {OUT_FILE} ({time.time()-t0:.1f}s)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"[45] FAILED: {e}")
        sys.exit(1)
