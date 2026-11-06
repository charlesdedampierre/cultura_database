"""Download the biography of every individual of the benchmark (data/benchmark_cultura.tsv).

Texts already downloaded (data/additions_texts.json and an earlier data/benchmark_texts.json) are reused. The benchmark includes the individuals added by 3_fill.py. A biography
that cannot be read (error, under MIN_TEXT characters, cross-reference page) is listed as failed.
Each text is saved to data/texts/{qid}.txt for the extraction agents, and all of
them to data/benchmark_texts.json.

Usage: .venv/bin/python notebooks/notebooks_polity_validation/scripts/5_texts.py
"""

import json
import time

import polars as pl
from tqdm import tqdm

from dictionaries import DATA, fetch

BENCHMARK = DATA / "benchmark_cultura.tsv"
TEXTS = DATA / "benchmark_texts.json"


def main():
    benchmark = pl.read_csv(BENCHMARK, separator="\t")
    earlier = json.loads((DATA / "additions_texts.json").read_text())
    if TEXTS.exists():
        earlier |= {person["qid"]: person["text"] for person in json.loads(TEXTS.read_text())}
    (DATA / "texts").mkdir(parents=True, exist_ok=True)
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
        (DATA / "texts" / f"{person['qid']}.txt").write_text(header + person["text"], encoding="utf-8")
    TEXTS.write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(found)} biographies, {sum(len(person['text']) for person in found):,} characters; {len(failed)} failed")
    for person in failed:
        print(f"  failed: {person['qid']} {person['label']} ({person['dictionary_name']}) {person['biography_url']}")


if __name__ == "__main__":
    main()
