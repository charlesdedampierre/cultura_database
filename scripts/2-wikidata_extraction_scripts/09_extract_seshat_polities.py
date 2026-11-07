"""Download the list of Seshat polities (id, name, long name, years) from the Seshat API into data/seshat/seshat_polities.json, read by enrichment 08_seshat_id.py for the Seshat long names."""

import json
from pathlib import Path

import requests
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "data" / "seshat" / "seshat_polities.json"
URL = "https://seshat-db.com/api/core/polities/?format=json&page_size=100"
FIELDS = ("id", "name", "long_name", "start_year", "end_year")


def main():
    polities = []
    url = URL
    progress = tqdm(desc="seshat polities", unit=" polities")
    while url:
        page = requests.get(url, timeout=60).json()
        polities += [{field: polity.get(field) for field in FIELDS} for polity in page["results"]]
        progress.total = page["count"]
        progress.update(len(page["results"]))
        url = page["next"]
    progress.close()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(polities, indent=1, ensure_ascii=False))
    print(f"{len(polities)} polities written to {OUTPUT}")


if __name__ == "__main__":
    main()
