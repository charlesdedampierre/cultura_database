"""Download the CBDB record of every individual in cbdb_sample.json from the CBDB API.

Each record is saved as the API returns it, keyed by Wikidata id, in
scripts/5-annotations/cbdb_validation/cbdb_persons.json. Records already downloaded are kept,
failed ones are retried once.

Usage: .venv/bin/python scripts/5-annotations/building_scripts/cbdb_extraction.py
"""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / "scripts" / "5-annotations" / "cbdb_validation"
SAMPLE = FOLDER / "cbdb_sample.json"
OUT = FOLDER / "cbdb_persons.json"
API = "https://cbdb.fas.harvard.edu/cbdbapi/person.php"
HEADERS = {"User-Agent": "cultura-database research (cdedampierre@bunka.ai)"}
WORKERS = 5


def person(cbdb_id):
    try:
        response = requests.get(API, params={"id": cbdb_id, "o": "json"}, headers=HEADERS, timeout=120)
        response.raise_for_status()
        return response.json()["Package"]["PersonAuthority"]["PersonInfo"]["Person"]
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None


def download(todo, records):
    with ThreadPoolExecutor(WORKERS) as pool:
        results = pool.map(lambda row: (row["qid"], person(row["cbdb_id"])), todo)
        for qid, record in tqdm(results, total=len(todo), desc="CBDB records"):
            if record is not None:
                records[qid] = record


def main():
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    records = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    for attempt in range(2):
        todo = [row for row in sample if row["qid"] not in records]
        print(f"{len(todo)} records to download, {len(sample) - len(todo)} already saved")
        download(todo, records)
        OUT.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    missing = [row["qid"] for row in sample if row["qid"] not in records]
    print(f"{len(records)} records saved to {OUT.relative_to(ROOT)}, {len(missing)} failed: {', '.join(missing[:10])}")


if __name__ == "__main__":
    main()
