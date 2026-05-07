"""
Run Gemini 2.5 Flash Lite (via OpenRouter) over the 10K Wikipedia pages we
extracted in `data/wiki_no_floruit_no_polity_sample/pages.jsonl`.

For each individual we ask the model to extract:
  - birth_year                 (int CE, negative for BCE, or null)
  - death_year                 (int CE / "still going" / null)
  - floruit_period_start       (int CE, negative for BCE, or null)
  - floruit_period_end         (int CE / "still going" / null)
  - polities                   (list of polity names, English; empty list if unknown)
  - confidence                 ("high" | "medium" | "low")
  - reasoning                  (1-3 sentences in English)

The whole response (including reasoning) MUST be in ENGLISH, even when the
source Wikipedia article is in another language.

Concurrency: ThreadPoolExecutor (HTTP-bound). Workers share an outbound
requests.Session per thread.

Estimated wall time @ 32 workers: ~5-10 min for 10k items
Estimated cost                  : ~$1-4 USD (most extracts are short)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAGES_PATH = PROJECT_ROOT / "data" / "wiki_no_floruit_no_polity_sample" / "pages.jsonl"
OUT_DIR = PROJECT_ROOT / "data" / "wiki_no_floruit_no_polity_sample"
OUT_PATH = OUT_DIR / "gemini_extractions.jsonl"
COST_PATH = OUT_DIR / "gemini_extractions_cost.md"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "google/gemini-2.5-flash-lite"

NUM_WORKERS = 32
EXTRACT_CHAR_CAP = 6000
LLM_TIMEOUT = 120
MAX_RETRIES = 4

SYSTEM_PROMPT = """You are an expert historian extracting biographical metadata from Wikipedia articles.

The article may be in any language. Your ENTIRE OUTPUT MUST BE IN ENGLISH — including
person names (transliterate where appropriate), polity names, and reasoning.

For the given article, extract:
  - birth_year:   integer CE, negative integer for BCE, or null
  - death_year:   integer CE, negative integer for BCE, the literal string "still going" (still alive), or null
  - floruit_period_start: integer year when the person became active in their main role, or null
  - floruit_period_end:   integer year when activity ended, "still going", or null
  - polities: a list of polities (countries, kingdoms, empires, dynasties, city-states, etc.)
              that the person was active in or a citizen of. Use English names
              (e.g. "Roman Empire", "Tang dynasty", "Kingdom of France", "United States").
              [] if unknown / not inferable.
  - confidence: "high" | "medium" | "low"
  - reasoning:  1-3 short sentences in English citing the evidence

Rules
- Use NEGATIVE integers for BCE (e.g. -44 for 44 BCE).
- For monarchs, floruit period = reign. For artists/scientists/etc., the productive career window.
- If the person is still active and there is no death date, set death_year and floruit_period_end to "still going".
- If you cannot infer a value with reasonable confidence, return null (not 0, not "unknown").
- Output STRICT JSON ONLY with EXACTLY these keys: birth_year, death_year, floruit_period_start, floruit_period_end, polities, confidence, reasoning. No prose around the JSON.
"""

# ---------------------------------------------------------------------------
# Per-thread requests session
# ---------------------------------------------------------------------------
_tls = threading.local()


def _session() -> requests.Session:
    if not hasattr(_tls, "s"):
        s = requests.Session()
        s.headers.update(
            {
                "Content-Type": "application/json",
                "HTTP-Referer": "https://bunka.ai/",
                "X-Title": "Cultura date+polity extraction (10k)",
            }
        )
        _tls.s = s
    return _tls.s


# ---------------------------------------------------------------------------
# Gemini call
# ---------------------------------------------------------------------------
def call_model(api_key: str, page: dict) -> dict:
    extract = (page.get("extract") or "")[:EXTRACT_CHAR_CAP]
    title = page.get("resolved_title") or page.get("title") or ""
    site = page.get("site") or ""
    description = page.get("description") or ""

    user_msg = (
        f"Wikipedia language site: {site}\n"
        f"Article title: {title}\n"
        f"Short description: {description}\n\n"
        f"--- ARTICLE LEAD ---\n{extract}\n--- END ARTICLE ---\n\n"
        "Extract the requested fields. Respond in English, JSON only."
    )
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "usage": {"include": True},
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    last_err: str = ""
    for attempt in range(MAX_RETRIES):
        try:
            r = _session().post(
                OPENROUTER_URL,
                headers=headers,
                json=body,
                timeout=LLM_TIMEOUT,
            )
        except requests.RequestException as e:
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(1.5 * (2 ** attempt))
            continue
        if r.status_code in (408, 409, 425, 429, 500, 502, 503, 504):
            last_err = f"http_{r.status_code}"
            time.sleep(1.5 * (2 ** attempt))
            continue
        if r.status_code != 200:
            return {"error": f"http_{r.status_code}: {r.text[:200]}"}
        try:
            data = r.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            usage = data.get("usage") or {}
            return {
                "extraction": parsed,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "cost_usd": usage.get("cost"),
            }
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(1.5 * (2 ** attempt))
    return {"error": last_err or "unknown"}


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def load_pages(path: Path) -> list[dict]:
    pages: list[dict] = []
    with path.open() as f:
        for line in f:
            r = json.loads(line)
            if r.get("ok") and r.get("extract"):
                pages.append(r)
    return pages


def load_already_done(path: Path) -> set[str]:
    done: set[str] = set()
    if not path.exists():
        return done
    with path.open() as f:
        for line in f:
            try:
                done.add(json.loads(line)["wikidata_id"])
            except (json.JSONDecodeError, KeyError):
                continue
    return done


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="cap how many items to process (for dry-runs)")
    parser.add_argument("--workers", type=int, default=NUM_WORKERS)
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("OPEN_ROUTER_API")
    if not api_key:
        print("ERROR: OPEN_ROUTER_API not set in .env", file=sys.stderr)
        return 1

    print(f"[info] reading pages from   {PAGES_PATH}")
    pages = load_pages(PAGES_PATH)
    print(f"[info] {len(pages):,} pages with non-empty extracts")

    already = load_already_done(OUT_PATH)
    if already:
        print(f"[info] resuming: {len(already):,} already processed")
        pages = [p for p in pages if p["wikidata_id"] not in already]

    if args.limit is not None:
        pages = pages[: args.limit]
        print(f"[info] limited to {len(pages):,} for this run")

    if not pages:
        print("[info] nothing to do.")
        return 0

    print(f"[info] model={MODEL}  workers={args.workers}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    totals = {"prompt": 0, "completion": 0, "cost": 0.0, "ok": 0, "fail": 0}
    totals_lock = threading.Lock()
    write_lock = threading.Lock()

    t0 = time.perf_counter()
    with OUT_PATH.open("a", encoding="utf-8") as out_fh, ThreadPoolExecutor(
        max_workers=args.workers
    ) as pool:
        def task(page: dict) -> dict:
            res = call_model(api_key, page)
            rec = {
                "wikidata_id": page["wikidata_id"],
                "site": page["site"],
                "title": page.get("resolved_title") or page.get("title"),
                "url": page.get("fullurl") or page.get("url"),
            }
            if "extraction" in res:
                rec["extraction"] = res["extraction"]
                rec["prompt_tokens"] = res.get("prompt_tokens")
                rec["completion_tokens"] = res.get("completion_tokens")
                rec["total_tokens"] = res.get("total_tokens")
                rec["cost_usd"] = res.get("cost_usd")
                with totals_lock:
                    if isinstance(res.get("prompt_tokens"), int):
                        totals["prompt"] += res["prompt_tokens"]
                    if isinstance(res.get("completion_tokens"), int):
                        totals["completion"] += res["completion_tokens"]
                    if isinstance(res.get("cost_usd"), (int, float)):
                        totals["cost"] += float(res["cost_usd"])
                    totals["ok"] += 1
            else:
                rec["error"] = res.get("error", "unknown")
                with totals_lock:
                    totals["fail"] += 1
            return rec

        futures = [pool.submit(task, p) for p in pages]
        pbar = tqdm(total=len(futures), desc="gemini", unit="page", mininterval=0.5)
        for fut in as_completed(futures):
            rec = fut.result()
            with write_lock:
                out_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out_fh.flush()
            with totals_lock:
                pbar.set_postfix(
                    ok=totals["ok"],
                    fail=totals["fail"],
                    cost_usd=f"{totals['cost']:.3f}",
                )
            pbar.update(1)
        pbar.close()

    dt = time.perf_counter() - t0
    summary = (
        f"# Gemini extraction over 10K Wikipedia pages\n\n"
        f"- Model: `{MODEL}`\n"
        f"- Items attempted: {totals['ok'] + totals['fail']:,}\n"
        f"- Successes: {totals['ok']:,}\n"
        f"- Failures : {totals['fail']:,}\n"
        f"- Wall clock: {dt/60:.2f} min\n"
        f"- Throughput: {(totals['ok']+totals['fail'])/dt:.2f} pages/s\n"
        f"- Total prompt tokens    : {totals['prompt']:,}\n"
        f"- Total completion tokens: {totals['completion']:,}\n"
        f"- Total cost (USD)       : ${totals['cost']:.4f}\n"
        f"- Avg cost per success   : ${(totals['cost']/totals['ok'] if totals['ok'] else 0):.6f}\n"
        f"- Output JSONL           : `{OUT_PATH}`\n"
    )
    COST_PATH.write_text(summary, encoding="utf-8")
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
