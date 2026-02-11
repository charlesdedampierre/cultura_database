"""
Run all processing steps for Cliopatria data.

Usage:
    python run_all.py

Steps:
    1. Extract and parse GeoJSON from zip
    2. Create SQLite database
    3. Enrich with Wikipedia URLs and Wikidata IDs
    4. Create hierarchy tables
"""

import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

STEPS = [
    ("01_extract_geojson.py", "Extracting GeoJSON"),
    ("02_create_database.py", "Creating database"),
    ("03_enrich_wikipedia.py", "Enriching Wikipedia/Wikidata"),
    ("04_create_hierarchy.py", "Creating hierarchy tables"),
]


def run_step(script_name: str, description: str):
    """Run a processing step."""
    print(f"\n{'='*60}")
    print(f"STEP: {description}")
    print(f"{'='*60}\n")

    script_path = SCRIPT_DIR / script_name
    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=SCRIPT_DIR
    )

    if result.returncode != 0:
        print(f"\n❌ ERROR: {script_name} failed with code {result.returncode}")
        sys.exit(1)

    print(f"\n✓ {description} complete")


def main():
    print("="*60)
    print("CLIOPATRIA DATA PROCESSING PIPELINE")
    print("="*60)

    for script_name, description in STEPS:
        run_step(script_name, description)

    print("\n" + "="*60)
    print("ALL STEPS COMPLETE")
    print("="*60)
    print(f"\nOutput database: {SCRIPT_DIR / 'data' / 'cliopatria.db'}")


if __name__ == "__main__":
    main()
