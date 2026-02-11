"""Extract instance type hierarchy for works from Wikidata.

For each unique work instance type, queries P31 (instance of) to get
the super-instance. Saves to data/extracted/works/work_instances.json.
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


def get_instance_of(instance_id: str) -> dict | None:
    """Get P31 (instance of) for a work instance type."""
    query = """
    SELECT ?subject ?subjectLabel ?instance ?instanceLabel
    WHERE {
      BIND(wd:%s AS ?subject)
      ?subject wdt:P31 ?instance.
      SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
    }
    """ % instance_id

    try:
        rows = sparql_query(query)
        if not rows:
            return None

        row = rows[0]
        super_url = row.get("instance", "")
        super_id = super_url.split("/")[-1] if super_url else None

        return {
            "instance_wikidata_id": instance_id,
            "instance_label": row.get("subjectLabel", ""),
            "super_instance_wikidata_id": super_id,
            "super_instance_label": row.get("instanceLabel", ""),
        }
    except Exception as e:
        print(f"  Error for {instance_id}: {e}")
        return None


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Collect unique instance IDs from both notable and authored works
    instance_ids = set()

    for filename in ["notable_works.json", "authored_works.json"]:
        filepath = os.path.join(OUTPUT_DIR, filename)
        if os.path.exists(filepath):
            with open(filepath) as f:
                works = json.load(f)
            for w in works:
                iid = w.get("instance_wikidata_id")
                if iid and iid.startswith("Q"):
                    instance_ids.add(iid)

    instance_ids = list(instance_ids)
    print(f"Extracting super-instances for {len(instance_ids)} work instance types...")

    with Pool(NUM_WORKERS) as p:
        results = list(tqdm(
            p.imap(get_instance_of, instance_ids),
            total=len(instance_ids),
            desc="Work instances",
        ))

    results = [r for r in results if r is not None]

    output_path = os.path.join(OUTPUT_DIR, "work_instances.json")
    with open(output_path, "w") as f:
        json.dump(results, f)

    print(f"Saved {len(results)} work instance types to {output_path}")


if __name__ == "__main__":
    main()
