"""Draw 50 of the 300 benchmark individuals, spread over regions as the 300 are, and download their biography.

Each region gets a sixth of its benchmark individuals (QUOTAS), drawn at random (seed 42). When a
biography cannot be read (error, under MIN_TEXT characters, cross-reference page), the next drawn
individual of the region is tried. Each text is saved to benchmark/benchmark50/texts/{qid}.txt for the
extraction agents, and all of them to benchmark/benchmark50/benchmark50_texts.json.

Usage: .venv/bin/python scripts/5-annotations/building_scripts/benchmark50_texts.py
"""

import json
import time
from pathlib import Path

import polars as pl
import requests
from tqdm import tqdm

from dictionary_texts import DICTIONARIES, MIN_TEXT, page_text

ROOT = Path(__file__).resolve().parents[3]
BENCHMARK = ROOT / "scripts" / "5-annotations" / "benchmark" / "benchmark_cultura.tsv"
FOLDER = ROOT / "scripts" / "5-annotations" / "benchmark" / "benchmark50"
SEED = 42
QUOTAS = {
    "East Asia": 7, "Middle East & North Africa": 7, "South & Central Asia": 6,
    "Western Europe": 5, "Northern Europe": 5, "Southern Europe": 5, "Eastern Europe": 5,
    "North America": 4, "Latin America": 4, "Sub-Saharan Africa": 1, "Oceania": 1,
}
SETTINGS = {dictionary["name"]: dictionary for dictionary in DICTIONARIES.values()}


def fetch(person):
    settings = SETTINGS.get(person["dictionary_name"], {})
    try:
        _, _, text = page_text(person["biography_url"], settings.get("selector"))
    except requests.RequestException:
        return None
    if len(text) < MIN_TEXT or any(mark in text for mark in settings.get("reject", ())):
        return None
    return text


def main():
    benchmark = pl.read_csv(BENCHMARK, separator="\t")
    (FOLDER / "texts").mkdir(parents=True, exist_ok=True)
    found = []
    for region, quota in tqdm(QUOTAS.items(), desc="regions"):
        people = benchmark.filter(pl.col("claude_estimated_region") == region).sort("qid").sample(fraction=1.0, shuffle=True, seed=SEED)
        drawn = []
        for person in people.iter_rows(named=True):
            if len(drawn) == quota:
                break
            text = fetch(person)
            time.sleep(1)
            if text:
                drawn.append({**person, "text": text})
        print(f"{region:28} {len(drawn)} / {quota}")
        found += drawn
    for person in found:
        header = f"Individual: {person['label']} ({person['qid']})\nDictionary: {person['dictionary_name']}\nURL: {person['biography_url']}\n\n"
        (FOLDER / "texts" / f"{person['qid']}.txt").write_text(header + person["text"], encoding="utf-8")
    (FOLDER / "benchmark50_texts.json").write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")
    characters = [len(person["text"]) for person in found]
    print(f"{len(found)} biographies, {sum(characters):,} characters (median {sorted(characters)[len(characters) // 2]:,})")


if __name__ == "__main__":
    main()
