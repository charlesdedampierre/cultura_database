"""
Sample 10,000 Wikipedia pages for individuals that have:
  - NO floruit period (floruit_period_start IS NULL AND floruit_period_end IS NULL)
  - NO polity assignment (not present in individuals_cliopatria)
  - At least one wikipedia.org sitelink

For each sampled individual we pick the en.wikipedia.org URL when available,
otherwise a random non-English Wikipedia URL.

We then fetch the lead extract via the MediaWiki action API in *batches of 20
titles per request* (well within Wikimedia rate-limit policy) and run the
batches in parallel across processes. tqdm shows page-level progress.

Estimated wall-clock time:
  - SQL sampling step: ~30-60 s
  - Parallel fetch (8 workers, 20 titles per request, retry-on-429):
        ~2-5 min for 10k pages

Output:
  data/wiki_no_floruit_no_polity_sample/sample_index.jsonl  (id, site, url, title)
  data/wiki_no_floruit_no_polity_sample/pages.jsonl         (one record per
                                                             individual; lead
                                                             extract + meta)
"""

from __future__ import annotations

import json
import multiprocessing as mp
import random
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "humans_clean.sqlite3"
OUT_DIR = PROJECT_ROOT / "data" / "wiki_no_floruit_no_polity_sample"
INDEX_PATH = OUT_DIR / "sample_index.jsonl"
PAGES_PATH = OUT_DIR / "pages.jsonl"

SAMPLE_SIZE = 10_000
N_WORKERS = 8
BATCH_SIZE = 20  # MediaWiki action API max for prop=extracts
RANDOM_SEED = 42
USER_AGENT = (
    "cultura_database-research/1.0 (Bunka Lab; cdedampierre@bunka.ai) "
    "python-requests"
)
REQUEST_TIMEOUT = 30
MAX_RETRIES = 5


# ---------------------------------------------------------------------------
# Step 1 - sample eligible individuals + pick a Wikipedia URL each
# ---------------------------------------------------------------------------
def sample_individuals(seed: int, sample_size: int):
    """Return list of (wikidata_id, site, title, url) tuples."""
    print(f"[1/3] Connecting to {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA temp_store = MEMORY;")
    cur = conn.cursor()

    print("[1/3] Building eligible-individuals temp table (~30-60s)...")
    t0 = time.perf_counter()
    cur.executescript(
        """
        DROP TABLE IF EXISTS _eligible;
        CREATE TEMP TABLE _eligible AS
        SELECT fp.wikidata_id
        FROM individuals_floruit_period fp
        LEFT JOIN individuals_cliopatria ic
               ON ic.wikidata_id = fp.wikidata_id
        WHERE fp.floruit_period_start IS NULL
          AND fp.floruit_period_end IS NULL
          AND ic.wikidata_id IS NULL;
        CREATE INDEX _eligible_idx ON _eligible(wikidata_id);
        """
    )
    n_eligible = cur.execute("SELECT COUNT(*) FROM _eligible").fetchone()[0]
    print(f"      eligible individuals (no floruit, no polity): {n_eligible:,}")

    print("[1/3] Pulling wikipedia sitelinks for eligible individuals...")
    cur.execute(
        """
        SELECT wl.wikidata_id, wl.site, wl.title, wl.url
        FROM wikimedia_links wl
        INNER JOIN _eligible e ON e.wikidata_id = wl.wikidata_id
        WHERE wl.site LIKE '%.wikipedia.org'
        """
    )

    by_id: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    pulled = 0
    pbar = tqdm(desc="rows", unit="row", mininterval=0.5)
    for wid, site, title, url in cur:
        if title is None:
            continue
        by_id[wid].append((site, title, url))
        pulled += 1
        pbar.update(1)
    pbar.close()
    print(
        f"      pulled {pulled:,} wikipedia sitelinks across "
        f"{len(by_id):,} distinct individuals"
    )

    rng = random.Random(seed)
    print(f"[1/3] Sampling {sample_size:,} individuals at random...")
    if len(by_id) < sample_size:
        raise RuntimeError(
            f"Only {len(by_id):,} eligible individuals have a wikipedia link"
        )
    sampled_ids = rng.sample(list(by_id.keys()), sample_size)

    chosen: list[tuple[str, str, str, str]] = []
    for wid in sampled_ids:
        links = by_id[wid]
        en = [link for link in links if link[0] == "en.wikipedia.org"]
        pick = en[0] if en else rng.choice(links)
        site, title, url = pick
        chosen.append((wid, site, title, url))

    n_en = sum(1 for r in chosen if r[1] == "en.wikipedia.org")
    print(
        f"      sample composition: {n_en:,} english / "
        f"{sample_size - n_en:,} other-language"
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with INDEX_PATH.open("w", encoding="utf-8") as f:
        for wid, site, title, url in chosen:
            f.write(
                json.dumps(
                    {"wikidata_id": wid, "site": site, "title": title, "url": url},
                    ensure_ascii=False,
                )
                + "\n"
            )
    print(f"      index written -> {INDEX_PATH} (in {time.perf_counter()-t0:.1f}s)")

    conn.close()
    return chosen


# ---------------------------------------------------------------------------
# Step 2 - fetch wikipedia page lead extracts in batches via the action API
# ---------------------------------------------------------------------------
_session: requests.Session | None = None


def _init_worker():
    global _session
    _session = requests.Session()
    _session.headers.update(
        {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    )


def _api_get_with_retry(url: str, params: dict) -> dict | None:
    """GET with retry on 429/503 honoring Retry-After."""
    assert _session is not None
    delay = 1.0
    for attempt in range(MAX_RETRIES):
        try:
            r = _session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        except requests.RequestException:
            time.sleep(delay)
            delay = min(delay * 2, 30)
            continue
        if r.status_code == 200:
            try:
                return r.json()
            except ValueError:
                return None
        if r.status_code in (429, 503):
            ra = r.headers.get("Retry-After")
            wait = float(ra) if ra and ra.isdigit() else delay
            time.sleep(min(wait, 60))
            delay = min(delay * 2, 30)
            continue
        # 4xx other -> give up
        return None
    return None


def _fetch_batch(args: tuple[str, list[tuple[str, str, str, str]]]) -> list[dict]:
    """Fetch a batch (<=20 titles) for a single wiki site."""
    site, items = args
    api = f"https://{site}/w/api.php"
    titles = [it[2] for it in items]
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "prop": "extracts|description|info",
        "explaintext": "1",
        "exintro": "1",
        "redirects": "1",
        "inprop": "url",
        "titles": "|".join(titles),
    }
    data = _api_get_with_retry(api, params)

    # Build a lookup from normalized title -> page result
    pages_by_title: dict[str, dict] = {}
    redirects: dict[str, str] = {}
    normalized: dict[str, str] = {}
    if data and "query" in data:
        q = data["query"]
        for n in q.get("normalized", []) or []:
            normalized[n["from"]] = n["to"]
        for r in q.get("redirects", []) or []:
            redirects[r["from"]] = r["to"]
        for p in q.get("pages", []) or []:
            pages_by_title[p.get("title", "")] = p

    out: list[dict] = []
    for wid, s, title, url in items:
        rec = {"wikidata_id": wid, "site": s, "title": title, "url": url}
        # walk normalization -> redirect chain
        resolved = normalized.get(title, title)
        resolved = redirects.get(resolved, resolved)
        page = pages_by_title.get(resolved)
        if page and not page.get("missing"):
            rec.update(
                ok=True,
                resolved_title=page.get("title"),
                pageid=page.get("pageid"),
                description=page.get("description"),
                extract=page.get("extract"),
                fullurl=page.get("fullurl"),
            )
        else:
            rec.update(ok=False, error="missing_or_no_response")
        out.append(rec)
    return out


def fetch_pages(items: list[tuple[str, str, str, str]]):
    print(
        f"[2/3] Fetching {len(items):,} pages with {N_WORKERS} workers, "
        f"{BATCH_SIZE} titles per request..."
    )

    # group by site, then split into batches
    by_site: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
    for it in items:
        by_site[it[1]].append(it)

    batches: list[tuple[str, list]] = []
    for site, lst in by_site.items():
        for i in range(0, len(lst), BATCH_SIZE):
            batches.append((site, lst[i : i + BATCH_SIZE]))
    print(f"      {len(batches):,} batches across {len(by_site):,} wiki sites")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n_ok = 0
    n_total = 0
    t0 = time.perf_counter()
    with PAGES_PATH.open("w", encoding="utf-8") as out_fh, mp.Pool(
        processes=N_WORKERS, initializer=_init_worker
    ) as pool:
        pbar = tqdm(total=len(items), desc="wiki", unit="page", mininterval=0.5)
        for batch_records in pool.imap_unordered(_fetch_batch, batches, chunksize=1):
            for rec in batch_records:
                out_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n_total += 1
                if rec.get("ok"):
                    n_ok += 1
            pbar.update(len(batch_records))
            pbar.set_postfix(ok=n_ok, fail=n_total - n_ok)
        pbar.close()
    dt = time.perf_counter() - t0
    print(
        f"      fetched OK: {n_ok:,}/{n_total:,}  "
        f"({n_ok/max(n_total,1)*100:.1f}%) in {dt/60:.1f} min  "
        f"({n_total/dt:.1f} pages/s)"
    )
    print(f"      pages written -> {PAGES_PATH}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(sample_size: int = SAMPLE_SIZE) -> int:
    items = sample_individuals(seed=RANDOM_SEED, sample_size=sample_size)
    fetch_pages(items)
    print("[3/3] done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
