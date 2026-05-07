"""
Refetch full Wikipedia article text for the ~466k cached entries in
data/wikipedia_pages_missing_dates/ whose `extract` field is empty.

Why this is needed
------------------
The original fetcher used `prop=extracts&exintro=1`, which returns ""
for articles that begin with an infobox/categories and jump directly
to a section heading (sports/politician/musician bios, very common).
Those articles do exist on Wikipedia; the extracts API just returned
nothing because the lead section was empty.

Why one-title-per-request
-------------------------
The `extracts` API only returns multiple extracts per request when
`exintro=1` is set (exlimit is forced to 1 otherwise). Since
`exintro=1` was the original failure cause, we MUST drop it — and
that means single-title requests. We compensate with high
concurrency + proper Retry-After backoff.

What it does
------------
1. Walks the cache, lists every JSON whose char_count == 0.
2. Spawns N_WORKERS threads, each pulling jobs from a shared queue.
3. Each worker calls MediaWiki: `prop=extracts&explaintext=1&maxlag=5`
   for a SINGLE title (no `exintro`). Honours Retry-After on 429/503.
4. Writes the extract back into the same JSON file in place.

Idempotent: re-running only refetches entries still empty.
Safe to run alongside readers that only consume already-populated entries.

Run
---
    .venv/bin/python scripts/ai_enrichment/refetch_empty_wikipedia_extracts.py
"""

from __future__ import annotations

import json
import queue
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote

import requests
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = PROJECT_ROOT / "data" / "wikipedia_pages_missing_dates"

USER_AGENT = "cultura-database-refetch/1.0 (research; cdedampierre@bunka.ai)"
N_WORKERS = 16
HTTP_TIMEOUT = 30
MAX_RETRIES = 5
RETRY_BASE_SLEEP = 1.5
PER_WORKER_DELAY = 0.05  # ~20 req/s/worker max → ~320 req/s aggregate ceiling


def title_from_url(url: str) -> str:
    return unquote(url.rsplit("/wiki/", 1)[-1]).replace("_", " ")


def host_from_url(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0]


# ---------- step 1: scan the cache ---------------------------------------


def collect_empty_entries() -> list[dict]:
    """Return list of {qid, host, wp_title, file_path} for every
    cached JSON whose extract is empty and has a Wikipedia URL.
    """
    entries: list[dict] = []
    n_total = 0
    n_no_url = 0
    n_error_files = 0

    shards = sorted(p for p in CACHE_DIR.iterdir() if p.is_dir())
    for shard in tqdm(shards, desc="indexing cache", unit="shard"):
        for f in shard.iterdir():
            if "error" in f.name:
                n_error_files += 1
                continue
            n_total += 1
            try:
                d = json.loads(f.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if (d.get("char_count") or 0) > 0 and (d.get("extract") or "").strip():
                continue
            url = d.get("wp_url") or ""
            if not url:
                n_no_url += 1
                continue
            entries.append(
                {
                    "qid": d["wikidata_id"],
                    "host": host_from_url(url),
                    "wp_title": d.get("wp_title") or title_from_url(url),
                    "file_path": f,
                }
            )

    print(
        f"  total files = {n_total:,}, error files = {n_error_files:,}, "
        f"empty needing refetch = {len(entries):,}, no-url skipped = {n_no_url:,}"
    )
    by_host = Counter(e["host"] for e in entries)
    print("  top 8 hosts:")
    for h, n in by_host.most_common(8):
        print(f"    {h:<28} {n:>8,}")
    return entries


# ---------- step 2: single-title fetch -----------------------------------


def fetch_one(session: requests.Session, host: str, title: str) -> str:
    """One title, no `exintro`. Returns the plain-text extract or ""."""
    params = {
        "action": "query",
        "format": "json",
        "formatversion": 2,
        "prop": "extracts",
        "explaintext": 1,
        "redirects": 1,
        "maxlag": 5,
        "titles": title,
    }
    url = f"https://{host}/w/api.php"
    for attempt in range(MAX_RETRIES):
        try:
            r = session.get(
                url,
                params=params,
                timeout=HTTP_TIMEOUT,
                headers={"User-Agent": USER_AGENT},
            )
            if r.status_code in (429, 503):
                delay = float(r.headers.get("Retry-After", "0")) or (
                    RETRY_BASE_SLEEP * (2**attempt)
                )
                time.sleep(min(delay, 60))
                continue
            r.raise_for_status()
            data = r.json()
            for p in data.get("query", {}).get("pages", []) or []:
                if p.get("missing"):
                    return ""
                return p.get("extract") or ""
            return ""
        except (requests.RequestException, ValueError):
            if attempt == MAX_RETRIES - 1:
                return ""
            time.sleep(RETRY_BASE_SLEEP * (2**attempt))
    return ""


def write_extract(file_path: Path, extract: str) -> None:
    try:
        d = json.loads(file_path.read_text())
    except (OSError, json.JSONDecodeError):
        return
    d["extract"] = extract
    d["char_count"] = len(extract)
    d["fetched_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    file_path.write_text(json.dumps(d, ensure_ascii=False))


# ---------- step 3: pool of workers reading from shared queue ------------


def worker_loop(
    job_q: queue.Queue,
    pbar: tqdm,
    counters_lock: threading.Lock,
    counters: dict,
) -> None:
    session = requests.Session()
    while True:
        item = job_q.get()
        if item is None:
            job_q.task_done()
            return
        try:
            extract = fetch_one(session, item["host"], item["wp_title"])
            write_extract(item["file_path"], extract)
            with counters_lock:
                if extract:
                    counters["filled"] += 1
                else:
                    counters["still_empty"] += 1
        except Exception:
            with counters_lock:
                counters["errors"] += 1
        finally:
            pbar.update(1)
            time.sleep(PER_WORKER_DELAY)
            job_q.task_done()


# ---------- main ---------------------------------------------------------


def main() -> int:
    if not CACHE_DIR.exists():
        print(f"ERROR: cache dir not found: {CACHE_DIR}")
        return 1

    print(f"Cache : {CACHE_DIR}")
    print(f"Workers: {N_WORKERS} threads, single-title requests, no exintro")
    print()
    print("Indexing cache...")
    entries = collect_empty_entries()
    if not entries:
        print("Nothing to refetch.")
        return 0

    total = len(entries)
    # ETA: ~250-500 ms per request, divided by N_WORKERS
    eta_min_lo = total * 0.25 / N_WORKERS / 60
    eta_min_hi = total * 0.5 / N_WORKERS / 60
    print(
        f"\nTotal to refetch: {total:,}\n"
        f"Estimated runtime: ~{eta_min_lo:.0f}-{eta_min_hi:.0f} min "
        f"(if Wikipedia keeps up; longer if 429s force backoff)\n"
    )

    job_q: queue.Queue = queue.Queue()
    for e in entries:
        job_q.put(e)
    for _ in range(N_WORKERS):
        job_q.put(None)  # poison pills

    counters_lock = threading.Lock()
    counters = {"filled": 0, "still_empty": 0, "errors": 0}

    with tqdm(total=total, desc="refetching", unit="page", smoothing=0.05) as pbar:
        with ThreadPoolExecutor(max_workers=N_WORKERS) as pool:
            for _ in range(N_WORKERS):
                pool.submit(worker_loop, job_q, pbar, counters_lock, counters)

    print()
    print(
        f"DONE: filled={counters['filled']:,}, "
        f"still_empty={counters['still_empty']:,}, "
        f"errors={counters['errors']:,}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
