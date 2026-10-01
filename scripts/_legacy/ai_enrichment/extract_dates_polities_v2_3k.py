"""
v2 of the Gemini date+polity extraction, with a prompt revised based on the
annotator-bad feedback:

  1. Do NOT fabricate floruit_period_end from a single event year.
  2. Only return "still going" when the article *explicitly* says the person
     is alive / currently active. Otherwise return null.
  3. If the article mentions any role / event year (e.g. consul since 2010,
     paper published in 2005), use it as a floruit anchor — do not return
     null when years exist in the text.
  4. Century-level evidence ("16th century") must be returned as a century
     range AND flagged with floruit_precision = "century".
  5. Also expose floruit_precision for downstream filtering:
        "year" | "decade" | "century" | "millennium" | "unknown"

Runs on 3,000 freshly sampled pages (excluding the 200 already shown to the
human annotator), with the same OpenRouter / threadpool stack as v1.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "wiki_no_floruit_no_polity_sample"
PAGES_PATH = DATA_DIR / "pages.jsonl"
ANNOTATOR_HTML = DATA_DIR / "gemini_annotator.html"
OUT_PATH = DATA_DIR / "gemini_extractions_v2b_3k.jsonl"
COST_PATH = DATA_DIR / "gemini_extractions_v2b_3k_cost.md"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "google/gemini-2.5-flash-lite"

NUM_WORKERS = 32
SAMPLE_SIZE = 3000
RANDOM_SEED = 7
EXTRACT_CHAR_CAP = 6000
LLM_TIMEOUT = 120
MAX_RETRIES = 4

SYSTEM_PROMPT = """You are an expert historian extracting biographical metadata from Wikipedia articles.

The article may be in any language. Your ENTIRE OUTPUT MUST BE IN ENGLISH —
including transliterated person names, polity names, and reasoning.

Return STRICT JSON with EXACTLY these keys:
  birth_year             integer CE (negative for BCE), or null
  death_year             integer CE (negative for BCE), or null
  floruit_period_start   integer year when the person became active, or null
  floruit_period_end     integer year when activity ended, or null
  floruit_precision      "year" | "decade" | "century" | "millennium" | "unknown"
  polities               list of polity names in English (e.g. "Roman Empire", "Tang dynasty",
                         "Kingdom of France", "United States"). [] if unknown.
  confidence             "high" | "medium" | "low"
  reasoning              1-3 short English sentences citing the evidence

CRITICAL RULES (these are based on real annotator feedback — follow them strictly):

A. Never fabricate a floruit_period_end from a single event year.
   Example: "won a bronze medal at the 1998 Asian Games" — set
   floruit_period_start = 1998 (anchor) and floruit_period_end = null.
   DO NOT write 1998-1998 just because that is the only year mentioned.

B. NEVER output the string "still going" or any other sentinel string for
   ANY field. Every date field is either an integer year or null. If the
   person is alive / currently active / has no known end of activity,
   return null for death_year and/or floruit_period_end. Likewise return
   null when the article is silent about a value — do not infer.

C. If the article gives ANY year associated with the person's activity
   (career start, role start, publication year, term in office, military
   campaign, etc.), use it to set floruit_period_start. Returning null for
   floruit_period_start when the text contains usable years is an error.
   Example: "consul since 2010" → floruit_period_start = 2010.

D. Century-level evidence: when the article only says e.g. "16th century",
   set floruit_period_start = 1500 (or -100, -1000 etc. for BCE),
   floruit_period_end = 1599, AND floruit_precision = "century".
   Use the standard mapping: nth century CE = (n-1)*100 to n*100 - 1.
   For BCE: nth century BCE = -n*100 to -(n-1)*100 - 1.

E. floruit_precision codifies how confident the YEAR bounds are:
     "year"      — exact years known (e.g. reign 1685-1715)
     "decade"    — known to within ~10 years
     "century"   — only century-level evidence
     "millennium"— only "ancient" / millennium-level evidence
     "unknown"   — both bounds null

F. Use NEGATIVE integers for BCE (e.g. -44 for 44 BCE).

G. For monarchs floruit = reign. For artists/scientists/etc. = the
   productive career window.

OUTPUT JSON ONLY — no prose around the object, no extra keys.
Every date field is either an integer or null. NEVER a string.
"""

_tls = threading.local()


def _session() -> requests.Session:
    if not hasattr(_tls, "s"):
        s = requests.Session()
        s.headers.update(
            {
                "Content-Type": "application/json",
                "HTTP-Referer": "https://bunka.ai/",
                "X-Title": "Cultura date+polity extraction v2 (3k)",
            }
        )
        _tls.s = s
    return _tls.s


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
    last_err = ""
    for attempt in range(MAX_RETRIES):
        try:
            r = _session().post(OPENROUTER_URL, headers=headers, json=body, timeout=LLM_TIMEOUT)
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


def _wikidata_ids_in_annotator() -> set[str]:
    """The 200 ids that are baked into the annotator HTML — exclude them
    from this round so the human reviewer sees fresh records."""
    if not ANNOTATOR_HTML.exists():
        return set()
    text = ANNOTATOR_HTML.read_text(encoding="utf-8")
    # the JSON payload sits inside <script id="DATA" type="application/json">
    start = text.find('id="DATA"')
    if start == -1:
        return set()
    open_idx = text.find(">", start) + 1
    close_idx = text.find("</script>", open_idx)
    payload = text[open_idx:close_idx].replace("<\\/", "</")
    try:
        records = json.loads(payload)
    except json.JSONDecodeError:
        return set()
    return {r["wikidata_id"] for r in records if "wikidata_id" in r}


def load_pages() -> list[dict]:
    out: list[dict] = []
    with PAGES_PATH.open() as f:
        for line in f:
            r = json.loads(line)
            if r.get("ok") and r.get("extract"):
                out.append(r)
    return out


def load_done(path: Path) -> set[str]:
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
    parser.add_argument("-n", type=int, default=SAMPLE_SIZE)
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    parser.add_argument("--workers", type=int, default=NUM_WORKERS)
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("OPEN_ROUTER_API")
    if not api_key:
        print("ERROR: OPEN_ROUTER_API not set in .env", file=sys.stderr)
        return 1

    print(f"[info] loading pages ...")
    pages = load_pages()
    print(f"[info] {len(pages):,} pages with non-empty extracts")

    excluded = _wikidata_ids_in_annotator()
    if excluded:
        print(f"[info] excluding {len(excluded):,} already shown to annotator")
        pages = [p for p in pages if p["wikidata_id"] not in excluded]

    rng = random.Random(args.seed)
    rng.shuffle(pages)
    pages = pages[: args.n]
    print(f"[info] sampled {len(pages):,} fresh pages (seed={args.seed})")

    already = load_done(OUT_PATH)
    if already:
        print(f"[info] resuming, {len(already):,} already done")
        pages = [p for p in pages if p["wikidata_id"] not in already]

    if not pages:
        print("[info] nothing to do")
        return 0

    print(f"[info] model={MODEL} workers={args.workers}")
    OUT_DIR = OUT_PATH.parent
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
                rec.update(
                    extraction=res["extraction"],
                    prompt_tokens=res.get("prompt_tokens"),
                    completion_tokens=res.get("completion_tokens"),
                    total_tokens=res.get("total_tokens"),
                    cost_usd=res.get("cost_usd"),
                )
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
        pbar = tqdm(total=len(futures), desc="gemini-v2", unit="page", mininterval=0.5)
        for fut in as_completed(futures):
            rec = fut.result()
            with write_lock:
                out_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out_fh.flush()
            with totals_lock:
                pbar.set_postfix(
                    ok=totals["ok"],
                    fail=totals["fail"],
                    cost=f"${totals['cost']:.3f}",
                )
            pbar.update(1)
        pbar.close()

    dt = time.perf_counter() - t0
    summary = (
        f"# Gemini v2 extraction (3,000 fresh pages, refined prompt)\n\n"
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
