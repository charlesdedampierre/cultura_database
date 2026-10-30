"""Download the biography of every individual of the benchmark of 300 (benchmark_cultura.tsv).

Texts already downloaded for the benchmark of 50 (benchmark50_texts.json) are reused. A biography
that cannot be read (error, under MIN_TEXT characters, cross-reference page) is listed as failed.
Each text is saved to benchmark/benchmark300/texts/{qid}.txt for the extraction agents, and all of
them to benchmark/benchmark300/benchmark300_texts.json.

Usage: .venv/bin/python scripts/5-annotations/building_scripts/benchmark300_texts.py
"""

import json
import time
from pathlib import Path

import polars as pl
from tqdm import tqdm

from benchmark50_texts import fetch

ROOT = Path(__file__).resolve().parents[3]
BENCHMARK = ROOT / "scripts" / "5-annotations" / "benchmark" / "benchmark_cultura.tsv"
EARLIER = ROOT / "scripts" / "5-annotations" / "benchmark" / "benchmark50" / "benchmark50_texts.json"
FOLDER = ROOT / "scripts" / "5-annotations" / "benchmark" / "benchmark300"


def main():
    benchmark = pl.read_csv(BENCHMARK, separator="\t")
    earlier = {person["qid"]: person["text"] for person in json.loads(EARLIER.read_text())}
    (FOLDER / "texts").mkdir(parents=True, exist_ok=True)
    found, failed = [], []
    for person in tqdm(benchmark.iter_rows(named=True), total=len(benchmark), desc="biographies"):
        text = earlier.get(person["qid"])
        if text is None:
            text = fetch(person)
            time.sleep(1)
        if text:
            found.append({**person, "text": text})
        else:
            failed.append(person)
    for person in found:
        header = f"Individual: {person['label']} ({person['qid']})\nDictionary: {person['dictionary_name']}\nURL: {person['biography_url']}\n\n"
        (FOLDER / "texts" / f"{person['qid']}.txt").write_text(header + person["text"], encoding="utf-8")
    (FOLDER / "benchmark300_texts.json").write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(found)} biographies, {sum(len(person['text']) for person in found):,} characters; {len(failed)} failed")
    for person in failed:
        print(f"  failed: {person['qid']} {person['label']} ({person['dictionary_name']}) {person['biography_url']}")


if __name__ == "__main__":
    main()
