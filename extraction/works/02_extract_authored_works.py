"""Extract works where individual is author (P50) or creator (P170).

Queries P50 (author) UNION P170 (creator), with P31, P571, P577.
Saves to data/extracted/works/authored_works.json.
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


def get_authored_works(wiki_id: str) -> list[dict]:
    """Get works authored/created by a single individual."""
    query = """
    SELECT ?subject ?subjectLabel ?object ?objectLabel
           ?instance ?instanceLabel ?inception ?publication_date
    WHERE {
      BIND(wd:%s AS ?subject)
      {
        ?object wdt:P50 ?subject.
        OPTIONAL { ?object wdt:P31 ?instance. }
        OPTIONAL { ?object wdt:P571 ?inception. }
        OPTIONAL { ?object wdt:P577 ?publication_date. }
      }
      UNION
      {
        ?object wdt:P170 ?subject.
        OPTIONAL { ?object wdt:P31 ?instance. }
        OPTIONAL { ?object wdt:P571 ?inception. }
        OPTIONAL { ?object wdt:P577 ?publication_date. }
      }
      SERVICE wikibase:label { bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }
    }
    """ % wiki_id

    try:
        rows = sparql_query(query)
        if not rows:
            return []

        works = []
        for row in rows:
            work_url = row.get("object", "")
            work_id = work_url.split("/")[-1] if work_url else ""
            instance_url = row.get("instance", "")
            instance_id = instance_url.split("/")[-1] if instance_url else None

            # Use inception, fall back to publication_date
            date = row.get("inception", "") or row.get("publication_date", "")

            works.append({
                "individual_wikidata_id": wiki_id,
                "work_wikidata_id": work_id,
                "work_name": row.get("objectLabel", ""),
                "instance_wikidata_id": instance_id,
                "instance_label": row.get("instanceLabel", ""),
                "inception": date,
                "relationship": "creator",
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
    print(f"Extracting authored works for {len(wiki_ids)} individuals...")

    with Pool(NUM_WORKERS) as p:
        results = list(tqdm(
            p.imap(get_authored_works, wiki_ids),
            total=len(wiki_ids),
            desc="Authored works",
        ))

    all_works = []
    for batch in results:
        all_works.extend(batch)

    output_path = os.path.join(OUTPUT_DIR, "authored_works.json")
    with open(output_path, "w") as f:
        json.dump(all_works, f)

    print(f"Saved {len(all_works)} authored works to {output_path}")


if __name__ == "__main__":
    main()
