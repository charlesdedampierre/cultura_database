"""Draw the 300-individual benchmark from population.parquet, spread over regions, periods and dictionaries.

Each region gets the number of individuals of QUOTAS. Within a region, individuals are drawn in
rounds: each round visits every period of birth the region has, and in each period takes a random
individual from the dictionary least drawn so far in the region. An individual is drawn once, with
the dictionary it was drawn from. Only individuals with the three Cultura life stages (pre-active, active
and post-active, each with its years, dated or estimated, in the life-stage polity export) enter the
benchmark. Each region's quota is split between two notability levels, read from the number of
Wikipedia editions with an article on the individual: famous (FAMOUS editions or more) and less
known; half of the quota (rounded up) goes to the famous, the rest to the less known, each taken in
drawing order, and a level short of candidates is completed from the other. The rest of the region's
candidates are kept in order as replacements, for when a biography cannot be downloaded.
Saved to data/sample.parquet.

Usage: .venv/bin/python notebooks/notebooks_polity_validation/scripts/2_sample.py
"""

import random
from collections import Counter
from pathlib import Path

import duckdb
import polars as pl

ROOT = Path(__file__).resolve().parents[3]
FOLDER = Path(__file__).resolve().parents[1] / "data"
DB = ROOT / "data" / "cultura" / "humans_clean_non_enriched_v3.duckdb"
POPULATION = FOLDER / "population.parquet"
STAGES_EXPORT = ROOT / "data" / "enriched_parquets" / "individual_life_stage_polities"
OUT = FOLDER / "sample.parquet"
SEED = 42
FAMOUS = 10
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
    """Individuals with a pre-active, an active and a post-active stage, each with its years, in the life-stage export."""
    stages = (pl.scan_parquet(STAGES_EXPORT / "batch_*.parquet").filter(pl.col("qid").is_in(pl.Series(qids).implode()))
              .filter(pl.col("start_year").is_not_null() & pl.col("end_year").is_not_null())
              .group_by("qid").agg(stages=pl.col("stage").n_unique()).filter(pl.col("stages") == 3).collect())
    return set(stages["qid"])


def wikipedia_editions(qids):
    connection = duckdb.connect(str(DB), read_only=True)
    connection.register("candidates", pl.DataFrame({"qid": qids}))
    return dict(connection.execute("""
        SELECT individual.entity.qid, len(list_filter(individual.sitelink, link -> link.site_url LIKE '%.wikipedia.org'))
        FROM individual JOIN candidates ON candidates.qid = individual.entity.qid
    """).fetchall())


def main():
    population = pl.read_parquet(POPULATION)
    qids = population["qid"].unique().to_list()
    eligible, editions = three_stages(qids), wikipedia_editions(qids)
    population = population.with_columns(wikipedia_editions=pl.col("qid").replace_strict(editions, default=0, return_dtype=pl.Int64))
    population = population.with_columns(notability=pl.when(pl.col("wikipedia_editions") >= FAMOUS).then(pl.lit("famous")).otherwise(pl.lit("less known")))
    rng = random.Random(SEED)
    rows = []
    for region, quota in QUOTAS.items():
        order = draw(population.filter(pl.col("region") == region).sort("qid", "dictionary").to_dicts(), rng)
        ranked = [{**row, "rank": rank, "three_stages": row["qid"] in eligible} for rank, row in enumerate(order)]
        levels = {level: [row["rank"] for row in ranked if row["three_stages"] and row["notability"] == level] for level in ("famous", "less known")}
        famous = min(len(levels["famous"]), max(-(-quota // 2), quota - len(levels["less known"])))
        chosen = set(levels["famous"][:famous] + levels["less known"][:quota - famous])
        rows += [{**row, "in_benchmark": row["rank"] in chosen} for row in ranked]
        print(f"{region:28} {famous:3} famous + {len(chosen) - famous:3} less known, of {len(levels['famous']):6} + {len(levels['less known']):6} candidates with three stages")
    sample = pl.DataFrame(rows)
    sample.write_parquet(OUT)
    print(f"{sample['in_benchmark'].sum()} individuals in the benchmark, {len(sample):,} ranked candidates saved to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
