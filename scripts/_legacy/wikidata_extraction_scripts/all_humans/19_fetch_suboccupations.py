"""
Fetch all sub-occupations of scientists and artists using QLever.
Uses transitive P279 (subclass of) to get all levels of sub-occupations.
"""

import json
import requests
from tqdm import tqdm

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"

# Root occupation Q-IDs
# Q901 = scientist (scientific researcher)
# Q2166621 = scientist
# Q483501 = artist

QUERY_SCIENTIST = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT DISTINCT ?suboccupation ?suboccupationLabel WHERE {
  ?suboccupation wdt:P279* wd:Q901 .
  ?suboccupation rdfs:label ?suboccupationLabel .
  FILTER(LANG(?suboccupationLabel) = "en")
}
"""

QUERY_ARTIST = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT DISTINCT ?suboccupation ?suboccupationLabel WHERE {
  ?suboccupation wdt:P279* wd:Q483501 .
  ?suboccupation rdfs:label ?suboccupationLabel .
  FILTER(LANG(?suboccupationLabel) = "en")
}
"""

OUTPUT_DIR = "data/all_humans"


def extract_qid(uri: str) -> str:
    """Extract Q-id from full URI."""
    if "/Q" in uri:
        return uri.split("/")[-1].rstrip(">")
    return uri


def fetch_suboccupations(query: str, name: str):
    print(f"\nQuerying QLever for all sub-occupations of {name}...")

    params = {
        "query": query,
        "action": "tsv_export"
    }

    response = requests.get(QLEVER_ENDPOINT, params=params, stream=True)
    response.raise_for_status()

    suboccupations = {}

    lines = response.iter_lines(decode_unicode=True)
    header = next(lines)  # Skip header

    for line in tqdm(lines, desc=f"Parsing {name} sub-occupations", unit=" items"):
        if line:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                qid = extract_qid(parts[0])
                label = parts[1].strip('"').rstrip('"@en')
                suboccupations[qid] = label

    print(f"Total {name} sub-occupations: {len(suboccupations):,}")
    return suboccupations


def main():
    # Fetch scientist sub-occupations
    scientist_suboccs = fetch_suboccupations(QUERY_SCIENTIST, "scientist (Q901)")

    # Fetch artist sub-occupations
    artist_suboccs = fetch_suboccupations(QUERY_ARTIST, "artist (Q483501)")

    # Save results
    output = {
        "scientist": {
            "root_qid": "Q901",
            "suboccupations": scientist_suboccs
        },
        "artist": {
            "root_qid": "Q483501",
            "suboccupations": artist_suboccs
        }
    }

    output_file = f"{OUTPUT_DIR}/suboccupations_scientist_artist.json"
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n=== Summary ===")
    print(f"Scientist sub-occupations: {len(scientist_suboccs):,}")
    print(f"Artist sub-occupations: {len(artist_suboccs):,}")
    print(f"Saved to {output_file}")


if __name__ == "__main__":
    main()
