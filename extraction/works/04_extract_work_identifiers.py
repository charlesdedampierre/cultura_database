"""Extract external identifiers for works from Wikidata.

Queries wikibase:ExternalId properties for each unique work.
Saves to data/extracted/works/work_identifiers.json.
"""

import json
import os
import sys
from multiprocessing import Pool

from tqdm import tqdm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from wikidata_api import sparql_query

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "extracted", "works")
NUM_WORKERS = 8


def get_work_identifiers(work_id: str) -> dict | None:
    """Get all external identifiers for a single work."""
    query = """
    SELECT ?p ?pLabel
    WHERE {
      BIND(wd:%s AS ?comp2)
      {
        ?comp2 ?wdt ?v .
        ?p wikibase:directClaim ?wdt ;
           wikibase:propertyType wikibase:ExternalId .
      }
      UNION { BIND(wd:%s AS ?p) }
      SERVICE wikibase:label { bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }
    }
    """ % (work_id, work_id)

    try:
        rows = sparql_query(query)
        if not rows:
            return None

        identifiers = []
        for row in rows:
            p_url = row.get("p", "")
            p_id = p_url.split("/")[-1]
            if p_id == work_id:
                continue
            identifiers.append({
                "identifier_wikidata_id": p_id,
                "identifier_name": row.get("pLabel", ""),
            })

        if not identifiers:
            return None

        return {
            "work_wikidata_id": work_id,
            "identifiers": identifiers,
        }
    except Exception as e:
        print(f"  Error for {work_id}: {e}")
        return None


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Collect unique work IDs from both notable and authored works
    work_ids = set()

    for filename in ["notable_works.json", "authored_works.json"]:
        filepath = os.path.join(OUTPUT_DIR, filename)
        if os.path.exists(filepath):
            with open(filepath) as f:
                works = json.load(f)
            for w in works:
                wid = w.get("work_wikidata_id")
                if wid and wid.startswith("Q"):
                    work_ids.add(wid)

    work_ids = list(work_ids)
    print(f"Extracting identifiers for {len(work_ids)} unique works...")

    with Pool(NUM_WORKERS) as p:
        results = list(tqdm(
            p.imap(get_work_identifiers, work_ids),
            total=len(work_ids),
            desc="Work identifiers",
        ))

    results = [r for r in results if r is not None]

    output_path = os.path.join(OUTPUT_DIR, "work_identifiers.json")
    with open(output_path, "w") as f:
        json.dump(results, f)

    print(f"Saved identifiers for {len(results)} works to {output_path}")


if __name__ == "__main__":
    main()
