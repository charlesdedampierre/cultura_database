"""Add individuals to the benchmark so that every region and century of birth has at least MINIMUM individuals.

The century is that of the Cultura birth year (start of the pre-active life stage in the life-stage
export). For each region and century with fewer than MINIMUM benchmark individuals, the candidates of
benchmark_sample.parquet (three life stages, not yet in the benchmark) are taken in drawing order until
the cell reaches MINIMUM, or until its candidates run out; a candidate whose biography cannot be read
is skipped. Saved to benchmark/benchmark_additions.parquet, with the downloaded texts in
benchmark/benchmark_additions_texts.json.

Usage: .venv/bin/python scripts/5-annotations/building_scripts/benchmark_fill.py
"""

import json
import time
from pathlib import Path

import polars as pl
from tqdm import tqdm

from benchmark50_texts import fetch
from benchmark_cultura import NAMES, URLS

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / "scripts" / "5-annotations" / "benchmark"
SAMPLE = FOLDER / "benchmark_sample.parquet"
STAGES_EXPORT = ROOT / "data" / "enriched_parquets" / "individual_life_stage_polities"
OUT = FOLDER / "benchmark_additions.parquet"
TEXTS = FOLDER / "benchmark_additions_texts.json"
MINIMUM = 3


def cultura_centuries(qids):
    births = (pl.scan_parquet(STAGES_EXPORT / "batch_*.parquet").filter((pl.col("stage") == "pre_active") & pl.col("qid").is_in(pl.Series(qids).implode()))
              .select("qid", pl.col("start_year").alias("cultura_birth_year")).collect())
    return births.with_columns(cultura_century=pl.col("cultura_birth_year") // 100 + 1)


def main():
    sample = pl.read_parquet(SAMPLE).filter(pl.col("three_stages"))
    sample = sample.join(cultura_centuries(sample["qid"].unique().to_list()), on="qid").sort("region", "rank")
    benchmark = sample.filter(pl.col("in_benchmark"))
    count = {(row["region"], row["cultura_century"]): row["len"] for row in benchmark.group_by("region", "cultura_century").len().iter_rows(named=True)}
    taken = set(benchmark["qid"])
    candidates = sample.filter(~pl.col("qid").is_in(pl.Series(list(taken)).implode()))
    cells = candidates.group_by("region", "cultura_century", maintain_order=True).agg(pl.struct(pl.all()).alias("rows"))
    added, texts = [], {}
    for cell in tqdm(cells.iter_rows(named=True), total=len(cells), desc="region and century"):
        key = (cell["region"], cell["cultura_century"])
        for row in cell["rows"]:
            if count.get(key, 0) >= MINIMUM:
                break
            if row["qid"] in taken:
                continue
            person = {**row, "dictionary_name": NAMES[row["dictionary"]], "biography_url": URLS[row["dictionary"]].format(row["dictionary_id"])}
            text = fetch(person)
            time.sleep(1)
            if text:
                taken.add(row["qid"])
                count[key] = count.get(key, 0) + 1
                added.append({**row, "region": cell["region"], "cultura_century": cell["cultura_century"]})
                texts[row["qid"]] = text
    additions = pl.DataFrame(added)
    additions.write_parquet(OUT)
    TEXTS.write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
    short = sum(1 for key in {(row["region"], row["cultura_century"]) for row in sample.iter_rows(named=True)} if count.get(key, 0) < MINIMUM)
    print(f"{len(additions)} individuals added; {short} region and century cells still under {MINIMUM} (not enough readable candidates)")


if __name__ == "__main__":
    main()
