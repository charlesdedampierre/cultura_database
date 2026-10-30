"""Draw the 300-individual benchmark from benchmark_population.parquet, spread over regions, periods and dictionaries.

Each region gets the number of individuals of QUOTAS. Within a region, individuals are drawn in
rounds: each round visits every period of birth the region has, and in each period takes a random
individual from the dictionary least drawn so far in the region. An individual is drawn once, with
the dictionary it was drawn from. Only individuals with the three Cultura life stages (early, active
and late, each with its years, dated or estimated, in the life-stage polity export) enter the
benchmark: the first QUOTAS eligible candidates of each region in drawing order. The rest of the
region's candidates are kept in order as replacements, for when a biography cannot be downloaded.
Saved to scripts/5-annotations/benchmark/benchmark_sample.parquet.

Usage: .venv/bin/python scripts/5-annotations/building_scripts/benchmark_sample.py
"""

import random
from collections import Counter
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / "scripts" / "5-annotations" / "benchmark"
POPULATION = FOLDER / "benchmark_population.parquet"
STAGES_EXPORT = ROOT / "data" / "enriched_parquets" / "individual_life_stage_polities"
OUT = FOLDER / "benchmark_sample.parquet"
SEED = 42
QUOTAS = {
    "Western Europe": 30, "Northern Europe": 30, "Southern Europe": 30, "Eastern Europe": 30,
    "Middle East & North Africa": 40, "East Asia": 40, "South & Central Asia": 35,
    "North America": 25, "Latin America": 25, "Sub-Saharan Africa": 10, "Oceania": 5,
}


def draw(candidates, rng):
    """Every candidate of the region, in drawing order: one per period and round, from the least drawn dictionary."""
    pools = {}
    for row in rng.sample(candidates, len(candidates)):
        pools.setdefault(row["period"], {}).setdefault(row["dictionary"], []).append(row)
    used, drawn, order = set(), Counter(), []
    while any(pool for dictionaries in pools.values() for pool in dictionaries.values()):
        for period in sorted(pools):
            available = {name: pool for name, pool in pools[period].items() if pool}
            while available:
                name = min(available, key=lambda name: (drawn[name], rng.random()))
                row = available[name].pop()
                if row["qid"] not in used:
                    used.add(row["qid"])
                    drawn[name] += 1
                    order.append(row)
                    break
                available = {name: pool for name, pool in pools[period].items() if pool}
    return order


def three_stages(qids):
    """Individuals with an early, an active and a late stage, each with its years, in the life-stage export."""
    stages = (pl.scan_parquet(STAGES_EXPORT / "batch_*.parquet").filter(pl.col("qid").is_in(pl.Series(qids).implode()))
              .filter(pl.col("start_year").is_not_null() & pl.col("end_year").is_not_null())
              .group_by("qid").agg(stages=pl.col("stage").n_unique()).filter(pl.col("stages") == 3).collect())
    return set(stages["qid"])


def main():
    population = pl.read_parquet(POPULATION)
    eligible = three_stages(population["qid"].unique().to_list())
    rng = random.Random(SEED)
    rows = []
    for region, quota in QUOTAS.items():
        order = draw(population.filter(pl.col("region") == region).sort("qid", "dictionary").to_dicts(), rng)
        taken = 0
        for rank, row in enumerate(order):
            has_stages = row["qid"] in eligible
            rows.append({**row, "rank": rank, "three_stages": has_stages, "in_benchmark": has_stages and taken < quota})
            taken += has_stages
        print(f"{region:28} {min(quota, taken):3} drawn of {taken:6} candidates with three stages ({len(order):6} in all)")
    sample = pl.DataFrame(rows)
    sample.write_parquet(OUT)
    print(f"{sample['in_benchmark'].sum()} individuals in the benchmark, {len(sample):,} ranked candidates saved to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
