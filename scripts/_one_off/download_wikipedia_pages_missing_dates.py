"""
Download Wikipedia plain-text extracts for every individual listed in
`data/individuals_no_date_with_wikipedia.csv`.

For each row:
  - prefer the English Wikipedia URL (`en_wikipedia_url`)
  - otherwise fall back to `any_wikipedia_url` (already chosen by the upstream
    pipeline, so this is the "another language picked at random" fallback)
  - skip rows that have neither

The MediaWiki Action API accepts up to 50 titles per call. We BATCH 50 rows
per request per host, so 487k pages fit in ~10k API calls instead of 487k.
This stays well under Wikimedia's anonymous rate limits.

Output:
  data/wikipedia_pages_missing_dates/<shard>/<wikidata_id>.json
where <shard> = wikidata_id[:4]  (e.g. "Q135" for "Q135440234"),
giving ~900 shards of ~500 files — friendly to APFS file listings.

Each JSON file:
  {
    "wikidata_id": "...",
    "name":        "...",
    "wp_lang":     "en",
    "wp_url":      "https://en.wikipedia.org/wiki/...",
    "wp_title":    "...",
    "extract":     "<full plain-text article>",
    "char_count":  12345,
    "fetched_at":  "ISO 8601"
  }

Resumable: existing `<qid>.json` files are skipped on re-run.
Failed rows write a `<qid>.error.json` sidecar; delete the sidecar to retry.

Run
---
    .venv/bin/python scripts/download_wikipedia_pages_missing_dates.py
    .venv/bin/python scripts/download_wikipedia_pages_missing_dates.py --limit 200    # test
    .venv/bin/python scripts/download_wikipedia_pages_missing_dates.py --workers 6
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

import requests
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_CSV = PROJECT_ROOT / "data" / "individuals_no_date_with_wikipedia.csv"
OUT_DIR = PROJECT_ROOT / "data" / "wikipedia_pages_missing_dates"
USER_AGENT = "cultura-database-bulk/1.0 (cdedampierre@bunka.ai)"
HTTP_TIMEOUT = 90
MAX_RETRIES = 6
DEFAULT_WORKERS = 4
BATCH_SIZE = 50  # MediaWiki anon limit on titles= per call


def shard_dir(qid: str) -> str:
    return qid[:4] if len(qid) >= 4 else qid


def out_path(qid: str) -> Path:
    return OUT_DIR / shard_dir(qid) / f"{qid}.json"


def err_path(qid: str) -> Path:
    return OUT_DIR / shard_dir(qid) / f"{qid}.error.json"


def url_to_host_title(url: str) -> tuple[str, str]:
    host = url.split("//", 1)[-1].split("/", 1)[0]
    title = unquote(url.rsplit("/wiki/", 1)[-1]).replace("_", " ")
    return host, title


# --- shared rate-limit cooldown ---------------------------------------------

_cooldown_lock = threading.Lock()
_cooldown_until = 0.0  # epoch seconds


def wait_for_cooldown() -> None:
    while True:
        with _cooldown_lock:
            wait = _cooldown_until - time.time()
        if wait <= 0:
            return
        time.sleep(min(wait, 5.0))


def trip_cooldown(seconds: float) -> None:
    global _cooldown_until
    target = time.time() + seconds
    with _cooldown_lock:
        if target > _cooldown_until:
            _cooldown_until = target


# --- batched fetch ----------------------------------------------------------


def fetch_batch(
    session: requests.Session, host: str, titles: list[str]
) -> dict[str, str]:
    """
    Return {title -> extract} for the given titles on `host`.
    Uses redirects=1, so the keys are the *requested* titles (we resolve back
    via the API's normalized + redirects maps).
    """
    api = f"https://{host}/w/api.php"
    params = {
        "action": "query",
        "prop": "extracts",
        "explaintext": 1,
        "redirects": 1,
        "format": "json",
        "titles": "|".join(titles),
    }
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        wait_for_cooldown()
        try:
            r = session.get(
                api,
                params=params,
                timeout=HTTP_TIMEOUT,
                headers={"User-Agent": USER_AGENT},
            )
            if r.status_code == 429:
                # Honor Retry-After when given; otherwise exponential backoff.
                ra = r.headers.get("Retry-After")
                wait = float(ra) if ra and ra.isdigit() else 8 * (2**attempt)
                trip_cooldown(wait)
                last_exc = requests.HTTPError(f"429 (waited {wait}s)")
                continue
            if r.status_code in (500, 502, 503, 504):
                time.sleep(2 * (2**attempt))
                last_exc = requests.HTTPError(f"{r.status_code} {r.reason}")
                continue
            r.raise_for_status()
            data = r.json()
            q = data.get("query", {}) or {}

            # title-resolution chain: input -> normalized -> redirect -> final
            mapping: dict[str, str] = {t: t for t in titles}
            for n in q.get("normalized", []) or []:
                if n["from"] in mapping:
                    mapping[n["from"]] = n["to"]
            # redirects can chain; iterate to a fixed point
            redirects = {r_["from"]: r_["to"] for r_ in (q.get("redirects") or [])}
            changed = True
            while changed:
                changed = False
                for k, v in list(mapping.items()):
                    if v in redirects:
                        mapping[k] = redirects[v]
                        changed = True

            extract_by_title = {
                p.get("title"): (p.get("extract") or "")
                for p in (q.get("pages") or {}).values()
                if p.get("title") is not None
            }
            return {t: extract_by_title.get(mapping[t], "") for t in titles}
        except (requests.RequestException, ValueError, KeyError) as e:
            last_exc = e
            time.sleep(2 * (2**attempt))
    raise last_exc if last_exc else RuntimeError("fetch_batch: unknown error")


# --- per-row work -----------------------------------------------------------


def write_row(row: dict, host: str, title: str, extract: str) -> str:
    qid = row["wikidata_id"]
    out_file = out_path(qid)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    url = (row.get("en_wikipedia_url") or "").strip() or (
        row.get("any_wikipedia_url") or ""
    ).strip()
    out_file.write_text(
        json.dumps(
            {
                "wikidata_id": qid,
                "name": row.get("name_en") or "",
                "wp_lang": host.split(".", 1)[0],
                "wp_url": url,
                "wp_title": title,
                "extract": extract,
                "char_count": len(extract),
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return "saved" if extract else "empty"


def write_err(row: dict, url: str, exc: Exception) -> None:
    qid = row["wikidata_id"]
    p = err_path(qid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "wikidata_id": qid,
                "wp_url": url,
                "error": f"{type(exc).__name__}: {exc}",
                "failed_at": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def process_batch(
    host: str, batch: list[tuple[dict, str, str]], session: requests.Session
) -> dict[str, int]:
    """
    Fetch one batch (up to BATCH_SIZE rows on a single host) and write outputs.
    Returns a small counts dict for the progress bar.
    """
    counts = {"saved": 0, "empty": 0, "error": 0}
    titles = [t for _, _, t in batch]
    try:
        extracts = fetch_batch(session, host, titles)
    except Exception as e:
        for row, url, _ in batch:
            write_err(row, url, e)
        counts["error"] += len(batch)
        return counts
    for row, url, title in batch:
        ext = extracts.get(title, "")
        try:
            status = write_row(row, host, title, ext)
            counts[status] += 1
        except Exception as e:
            write_err(row, url, e)
            counts["error"] += 1
    return counts


# --- driver -----------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="for testing: only process N rows (after skipping already-saved)",
    )
    args = ap.parse_args()

    if not INPUT_CSV.exists():
        print(f"ERROR: {INPUT_CSV} missing", file=sys.stderr)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load CSV, filter to rows that need fetching, group by host.
    pending_by_host: dict[str, list[tuple[dict, str, str]]] = defaultdict(list)
    skipped = 0
    no_url = 0
    with INPUT_CSV.open() as f:
        for row in csv.DictReader(f):
            qid = row["wikidata_id"]
            if out_path(qid).exists():
                skipped += 1
                continue
            url = (row.get("en_wikipedia_url") or "").strip() or (
                row.get("any_wikipedia_url") or ""
            ).strip()
            if not url:
                no_url += 1
                continue
            host, title = url_to_host_title(url)
            pending_by_host[host].append((row, url, title))

    total_pending = sum(len(v) for v in pending_by_host.values())
    if args.limit and total_pending > args.limit:
        # trim deterministically: round-robin across hosts up to limit
        budget = args.limit
        new: dict[str, list] = defaultdict(list)
        host_iters = {h: iter(rows) for h, rows in pending_by_host.items()}
        while budget > 0 and host_iters:
            empties = []
            for h, it in list(host_iters.items()):
                try:
                    new[h].append(next(it))
                    budget -= 1
                    if budget == 0:
                        break
                except StopIteration:
                    empties.append(h)
            for h in empties:
                host_iters.pop(h, None)
        pending_by_host = new
        total_pending = sum(len(v) for v in pending_by_host.values())

    print(f"Source     : {INPUT_CSV}")
    print(f"Output     : {OUT_DIR}")
    print(f"Already on disk (skipped) : {skipped:,}")
    print(f"Rows without URL          : {no_url:,}")
    print(f"Pending fetch             : {total_pending:,}")
    print(f"Hosts                     : {len(pending_by_host)}")
    print(f"Workers                   : {args.workers}")
    print(f"Batch size                : {BATCH_SIZE} titles/call")
    print(flush=True)

    # Build batches: each batch is (host, list[(row,url,title)]) of <= BATCH_SIZE.
    batches: list[tuple[str, list[tuple[dict, str, str]]]] = []
    for host, rows in pending_by_host.items():
        for i in range(0, len(rows), BATCH_SIZE):
            batches.append((host, rows[i : i + BATCH_SIZE]))

    counts = {"saved": 0, "empty": 0, "error": 0}
    session = requests.Session()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(process_batch, h, b, session) for h, b in batches]
        with tqdm(total=total_pending, desc="Wikipedia", unit="page") as bar:
            for fut in as_completed(futs):
                c = fut.result()
                for k, v in c.items():
                    counts[k] = counts.get(k, 0) + v
                bar.update(c["saved"] + c["empty"] + c["error"])

    print(
        "DONE: "
        + ", ".join(f"{k}={v:,}" for k, v in sorted(counts.items()))
        + f" (skipped_pre={skipped:,}, no_url={no_url:,})",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
