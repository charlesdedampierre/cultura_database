"""Extract notable works (P800) for each individual from Wikidata.

Queries P800 (notable work), P31 (instance of), P571 (inception).
Saves to data/extracted/works/notable_works.json.
"""

import json
import os
import sys
from multiprocessing import Pool

from tqdm import tqdm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from wikidata_api import sparql_query

INDIVIDUALS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "extracted", "individuals")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "extracted", "works")
NUM_WORKERS = 8


def get_notable_works(wiki_id: str) -> list[dict]:
    """Get notable works for a single individual."""
    query = """
    SELECT ?subject ?subjectLabel ?work ?workLabel ?instance ?inception ?instanceLabel
    WHERE {
      BIND(wd:%s AS ?subject)
      ?subject wdt:P800 ?work.
      OPTIONAL { ?work wdt:P31 ?instance }
      OPTIONAL { ?work wdt:P571 ?inception }
      SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
    }
    """ % wiki_id

    try:
        rows = sparql_query(query)
        if not rows:
            return []

        works = []
        for row in rows:
            work_url = row.get("work", "")
            work_id = work_url.split("/")[-1] if work_url else ""
            instance_url = row.get("instance", "")
            instance_id = instance_url.split("/")[-1] if instance_url else None

            works.append({
                "individual_wikidata_id": wiki_id,
                "work_wikidata_id": work_id,
                "work_name": row.get("workLabel", ""),
                "instance_wikidata_id": instance_id,
                "instance_label": row.get("instanceLabel", ""),
                "inception": row.get("inception", ""),
                "relationship": "notable_work",
            })

        return works
    except Exception as e:
        print(f"  Error for {wiki_id}: {e}")
        return []


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    individuals_path = os.path.join(INDIVIDUALS_DIR, "individuals.json")
    with open(individuals_path) as f:
        individuals = json.load(f)

    wiki_ids = [ind["wikidata_id"] for ind in individuals]
    print(f"Extracting notable works for {len(wiki_ids)} individuals...")

    with Pool(NUM_WORKERS) as p:
        results = list(tqdm(
            p.imap(get_notable_works, wiki_ids),
            total=len(wiki_ids),
            desc="Notable works",
        ))

    # Flatten
    all_works = []
    for batch in results:
        all_works.extend(batch)

    output_path = os.path.join(OUTPUT_DIR, "notable_works.json")
    with open(output_path, "w") as f:
        json.dump(all_works, f)

    print(f"Saved {len(all_works)} notable works to {output_path}")


if __name__ == "__main__":
    main()
