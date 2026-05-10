"""Speed-test inception (P571) and publication (P577) extraction for the
distinct works in `data/humans_clean.sqlite3`.

Why
---
The full set is ~17.06M unique work_ids. Before launching the bulk run we
benchmark a few VALUES-chunk sizes and a few thread counts so we pick a
config that keeps QLever happy and finishes in a reasonable time.

Tested grid
-----------
- chunk sizes:   1000, 2500, 5000, 10000  (rows per VALUES clause)
- thread counts: 1, 8, 15                  (concurrent QLever requests)
- total sample:  50,000 work_ids drawn from the works table

For each (chunk, threads) combo we measure wall time and works/second on
both P571 and P577 queries.

Run
---
    python scripts/wikidata_extraction_scripts_v2/18_speed_test_work_dates.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wikidata import extract_qid, qlever_stream  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "humans_clean.sqlite3"
SAMPLE_SIZE = 50_000

QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX psv: <http://www.wikidata.org/prop/statement/value/>
PREFIX wikibase: <http://wikiba.se/ontology#>

SELECT ?work ?date ?precision WHERE {{
  VALUES ?work {{ {values} }}
  ?work p:{prop} ?stmt .
  ?stmt psv:{prop} ?val .
  ?val wikibase:timeValue ?date .
  ?val wikibase:timePrecision ?precision .
}}
"""


def load_sample(n: int) -> list[str]:
    con = sqlite3.connect(str(DB_PATH))
    cur = con.execute(
        "SELECT DISTINCT work_id FROM works WHERE work_id LIKE 'Q%' LIMIT ?",
        (n,),
    )
    out = [r[0] for r in cur.fetchall()]
    con.close()
    return out


def chunked(seq: list[str], size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def fetch_chunk(qids: list[str], prop: str) -> int:
    values = " ".join(f"wd:{q}" for q in qids)
    query = QUERY.format(values=values, prop=prop)
    n = 0
    for row in qlever_stream(query):
        if len(row) < 3:
            continue
        if extract_qid(row[0]).startswith("Q"):
            n += 1
    return n


def run_combo(qids: list[str], prop: str, chunk: int, threads: int) -> tuple[float, int]:
    t0 = time.time()
    rows = 0
    chunks = list(chunked(qids, chunk))
    if threads == 1:
        for c in tqdm(chunks, desc=f"  {prop} chunk={chunk} thr=1", leave=False):
            rows += fetch_chunk(c, prop)
    else:
        with ThreadPoolExecutor(max_workers=threads) as pool:
            futures = [pool.submit(fetch_chunk, c, prop) for c in chunks]
            for fut in tqdm(as_completed(futures), total=len(futures),
                            desc=f"  {prop} chunk={chunk} thr={threads}", leave=False):
                rows += fut.result()
    return time.time() - t0, rows


def main():
    print(f"[18] DB: {DB_PATH}")
    print(f"[18] sample size: {SAMPLE_SIZE:,} work_ids")
    qids = load_sample(SAMPLE_SIZE)
    print(f"[18] loaded {len(qids):,} work_ids")
    print()

    grid: list[tuple[int, int]] = [
        (1000, 1), (2500, 1), (5000, 1),
        (5000, 8), (5000, 15),
        (10000, 8), (10000, 15),
    ]

    results = []
    for prop in ("P571", "P577"):
        print(f"=== {prop} ===")
        for chunk, threads in grid:
            dt, rows = run_combo(qids, prop, chunk, threads)
            rate = len(qids) / dt
            row_rate = rows / dt
            print(f"  chunk={chunk:>5} threads={threads:>2} -> "
                  f"{dt:>6.1f}s  {rate:>8,.0f} works/s  "
                  f"{rows:>6,} hits  {row_rate:>7,.0f} hits/s")
            results.append((prop, chunk, threads, dt, rows))
        print()

    # Best-by-throughput recommendation per prop
    print("=== best (works/sec) per prop ===")
    for prop in ("P571", "P577"):
        best = min((r for r in results if r[0] == prop), key=lambda r: r[3])
        works_per_sec = SAMPLE_SIZE / best[3]
        eta_full = 17_060_996 / works_per_sec
        print(f"  {prop}: chunk={best[1]} threads={best[2]} "
              f"-> {works_per_sec:,.0f} works/s, "
              f"ETA over 17.06M works: {eta_full/60:.1f} min")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
