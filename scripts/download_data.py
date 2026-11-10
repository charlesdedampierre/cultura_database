"""Download the Cultura Database from Zenodo (doi:10.5281/zenodo.24110595) through the Zenodo REST API.

By default only the simplified database is fetched: cultura_database_V4.csv.zip (395 MB), unzipped into data/exports/.
With --duckdb, the complete database cultura_database_V4.duckdb (13.7 GB) is also fetched, into data/cultura/.
Every file is checked against the checksum Zenodo publishes.

    python scripts/download_data.py            # the CSV
    python scripts/download_data.py --duckdb   # the CSV and the DuckDB file
"""

import argparse
import hashlib
import zipfile
from pathlib import Path

import requests
from tqdm import tqdm

RECORD = "24110595"
API = f"https://zenodo.org/api/records/{RECORD}"
ROOT = Path(__file__).resolve().parents[1]
CSV_ZIP = "cultura_database_V4.csv.zip"
DUCKDB = "cultura_database_V4.duckdb"
HEADERS = {"User-Agent": "cultura-database-download/1.0"}
CHUNK = 1 << 20  # 1 MB


def record_files():
    """The record's files by name, with their download link and checksum."""
    response = requests.get(API, headers=HEADERS, timeout=60)
    if response.status_code == 404:
        raise SystemExit(f"Zenodo record {RECORD} not found: it may not be published yet ({API})")
    response.raise_for_status()
    return {file["key"]: file for file in response.json()["files"]}


def download(file, target):
    """Stream one file to target with a progress bar, then check its checksum (Zenodo gives 'md5:<hex>')."""
    algorithm, expected = file["checksum"].split(":", 1)
    digest = hashlib.new(algorithm)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    with requests.get(file["links"]["self"], headers=HEADERS, stream=True, timeout=60) as response:
        response.raise_for_status()
        with partial.open("wb") as handle, tqdm(total=file["size"], unit="B", unit_scale=True, desc=file["key"]) as progress:
            for chunk in response.iter_content(CHUNK):
                handle.write(chunk)
                digest.update(chunk)
                progress.update(len(chunk))
    if digest.hexdigest() != expected:
        partial.unlink()
        raise SystemExit(f"{file['key']}: checksum mismatch, download removed; please retry")
    partial.rename(target)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--duckdb", action="store_true", help=f"also download {DUCKDB} (13.7 GB)")
    args = parser.parse_args()

    files = record_files()
    archive = download(files[CSV_ZIP], ROOT / "data" / "cultura" / CSV_ZIP)
    with zipfile.ZipFile(archive) as opened:
        opened.extractall(ROOT / "data" / "exports")
    print(f"CSV ready: {ROOT / 'data' / 'exports' / 'cultura_database_V4.csv'}")

    if args.duckdb:
        database = download(files[DUCKDB], ROOT / "data" / "cultura" / DUCKDB)
        print(f"DuckDB ready: {database}")


if __name__ == "__main__":
    main()
