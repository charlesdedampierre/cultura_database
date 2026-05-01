"""
Fetch all Q5 (human) sitelinks (Wikipedia pages, etc.) using QLever bulk query.
"""

import json
import requests
from tqdm import tqdm
from collections import defaultdict

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"

QUERY = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX schema: <http://schema.org/>

SELECT ?human ?sitelink WHERE {
  ?human wdt:P31 wd:Q5 .
  ?sitelink schema:about ?human .
}
"""

OUTPUT_FILE = "data/all_humans/all_human_sitelinks.json"


def extract_qid(uri: str) -> str:
    if "/Q" in uri:
        return uri.split("/")[-1].rstrip(">")
    return uri


def fetch_all_sitelinks():
    print("Querying QLever for all human sitelinks...")

    params = {
        "query": QUERY,
        "action": "tsv_export"
    }

    response = requests.get(QLEVER_ENDPOINT, params=params, stream=True)
    response.raise_for_status()

    # Store as dict: human_id -> list of sitelink URLs
    human_sitelinks = defaultdict(list)

    lines = response.iter_lines(decode_unicode=True)
    header = next(lines)

    for line in tqdm(lines, desc="Parsing", unit=" rows"):
        if line:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                human_id = extract_qid(parts[0])
                sitelink = parts[1].strip("<>")
                human_sitelinks[human_id].append(sitelink)

    print(f"\nTotal humans with sitelinks: {len(human_sitelinks):,}")
    total_links = sum(len(links) for links in human_sitelinks.values())
    print(f"Total sitelinks: {total_links:,}")

    with open(OUTPUT_FILE, "w") as f:
        json.dump(dict(human_sitelinks), f)

    print(f"Saved to {OUTPUT_FILE}")
    return human_sitelinks


if __name__ == "__main__":
    fetch_all_sitelinks()
