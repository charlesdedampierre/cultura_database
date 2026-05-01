"""Path A — step 2 (speed test).

Benchmark per-property identifier extraction from QLever using a fixed
sample of 60 representative properties drawn from the canonical list.
Tests batch sizes 10, 25, 50, 100 with 15 worker threads each, plus a
serial baseline. Reports rows/sec, completion-time, and a recommended
batch size for the full run (script 47).

The "batch size" here means: how many properties each worker thread is
asked to process before reporting back. We do NOT batch QLever calls
(QLever calls are one-property-per-call) — we batch property-list chunks
across threads.
"""
from __future__ import annotations

import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
PROP_LIST = ROOT / "data" / "all_humans" / "all_external_id_properties.json"
TASK_LOG = ROOT / "task.log"
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "identifier_extraction_v2.log"
SPEED_REPORT = LOG_DIR / "identifier_extraction_v2_speed_test.json"

QLEVER = "https://qlever.cs.uni-freiburg.de/api/wikidata"
HEADERS = {"User-Agent": "cultura-database-research/1.0 (cdedampierre@bunka.ai)"}

THREADS = 15
SAMPLE_SIZE = 60  # properties to use in the speed test
BATCH_SIZES = [10, 25, 50, 100]
SEED = 0


def log(msg: str) -> None:
    stamped = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(stamped, flush=True)
    LOG_DIR.mkdir(exist_ok=True)
    with TASK_LOG.open("a") as f:
        f.write(stamped + "\n")
    with LOG_FILE.open("a") as f:
        f.write(stamped + "\n")


def fetch_property(pid: str) -> tuple[str, int, float, str | None]:
    """Return (pid, n_rows, elapsed_seconds, error_or_None)."""
    query = f"""
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?human ?value WHERE {{
  ?human wdt:P31 wd:Q5 .
  ?human wdt:{pid} ?value .
}}
"""
    t0 = time.time()
    try:
        r = requests.get(
            QLEVER,
            params={"query": query, "action": "tsv_export"},
            headers=HEADERS,
            timeout=300,
            stream=True,
        )
        r.raise_for_status()
        n = -1  # subtract header
        for _ in r.iter_lines(decode_unicode=True):
            n += 1
        return pid, max(n, 0), time.time() - t0, None
    except Exception as e:
        return pid, 0, time.time() - t0, str(e)


def run_in_chunks(props: list[str], threads: int, chunk_size: int) -> dict:
    """Process props in chunks of `chunk_size` properties; threads work in parallel."""
    t0 = time.time()
    all_results = []
    for i in range(0, len(props), chunk_size):
        chunk = props[i:i + chunk_size]
        with ThreadPoolExecutor(max_workers=threads) as ex:
            for f in as_completed([ex.submit(fetch_property, p) for p in chunk]):
                all_results.append(f.result())
    total_rows = sum(r[1] for r in all_results)
    elapsed = time.time() - t0
    n_errors = sum(1 for r in all_results if r[3])
    return {
        "elapsed_s": round(elapsed, 2),
        "rows_per_s": round(total_rows / max(elapsed, 0.01), 1),
        "props_per_s": round(len(props) / max(elapsed, 0.01), 2),
        "total_rows": total_rows,
        "errors": n_errors,
    }


def main():
    if not PROP_LIST.exists():
        log("[46] property list not found; run script 45 first")
        sys.exit(1)

    data = json.load(PROP_LIST.open())
    all_props = [p["property_id"] for p in data["properties"]]
    rng = random.Random(SEED)
    sample = rng.sample(all_props, min(SAMPLE_SIZE, len(all_props)))
    log(f"[46] Speed test: {SAMPLE_SIZE} random properties, {THREADS} threads, "
        f"batch sizes {BATCH_SIZES}")

    report = {"sample_size": SAMPLE_SIZE, "threads": THREADS, "results": {}}

    log("[46]   warm-up: 1 query")
    fetch_property(sample[0])

    for chunk_size in BATCH_SIZES:
        log(f"[46]   benchmarking chunk_size={chunk_size}...")
        r = run_in_chunks(sample, THREADS, chunk_size)
        log(f"[46]     {r}")
        report["results"][str(chunk_size)] = r

    best = max(report["results"].items(), key=lambda kv: kv[1]["props_per_s"])
    report["recommended_batch_size"] = int(best[0])
    log(f"[46] Recommended batch size: {best[0]} ({best[1]['props_per_s']} props/s)")

    SPEED_REPORT.write_text(json.dumps(report, indent=2))
    log(f"[46] Wrote {SPEED_REPORT}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"[46] FAILED: {e}")
        sys.exit(1)
