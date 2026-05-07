"""
Test: extract floruit period from Wikipedia for individuals that have a polity
but no floruit period assigned.

Pipeline
--------
1. Sample 100 rows from `individuals_cliopatria` where polity is set and
   floruit_period_start is NULL, restricted to people who have at least one
   Wikipedia page in `wikimedia_links`.
2. Pick the English Wikipedia link if it exists; otherwise pick a random
   non-English Wikipedia link.
3. Download the plain-text extract of the article via the MediaWiki API.
4. Ask Gemini 3 Flash Preview (via OpenRouter) to extract a floruit period
   with reasoning, returning strict JSON.
5. Write a CSV with one row per individual and a Markdown report logging
   the API cost of the run.

API key: OPEN_ROUTER_API in .env
DB     : DB_PATH in .env (defaults to data/humans_clean.sqlite3)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sqlite3
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
DEFAULT_DB = PROJECT_ROOT / "data" / "humans_clean.sqlite3"
OUT_DIR = Path(__file__).resolve().parent

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "google/gemini-2.5-flash-lite"

SAMPLE_SIZE = 100
WIKI_EXTRACT_CHARS = 8000  # truncate plain-text article to this many chars
HTTP_TIMEOUT = 60
LLM_TIMEOUT = 120
MAX_RETRIES = 3
RANDOM_SEED = 42
NUM_WORKERS = 8  # parallel HTTP workers (I/O-bound, threads are ideal)

SYSTEM_PROMPT = """You are an expert historian extracting biographical dates.

Given an English (or foreign-language) Wikipedia article about a person, 
 Extratc the follwijg inromaiton if you find them:
 - birthdayte
 - deathdate
 - flrout periods the years during which they were active in their primary occupation (career, public life, scholarly work, reign, etc.).
   "reasoning":            "<2-4 sentence explanation citing specific evidence from the article>"

   - any dated relateds to the individial (if you don't knwo what it means, jsut extratc the dates)





Rules
- If you fidn the dates as century, extratc the centruy precision or even millenia preicson
- If the article is too sparse to infer anything reliable, just answer null
- Use NEGATIVE integers for BCE years (e.g. -44 for 44 BCE).
- Output JSON ONLY. No prose around it. No extra fields.
"""


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Step 1: pick the sample
# ---------------------------------------------------------------------------

PAST_POLITY_CUTOFF = 1800  # MAX(to_year) below this -> "past" polity


def _query_sample(conn: sqlite3.Connection, n: int, era: str) -> list[dict]:
    """era = 'past'  -> polity max(to_year) < cutoff
    era = 'modern' -> polity max(to_year) >= cutoff (or no period info)"""
    if era == "past":
        clause = "max_to < ?"
    else:
        clause = "(max_to IS NULL OR max_to >= ?)"
    sql = f"""
    WITH polity_end AS (
        SELECT polity_id, MAX(to_year) AS max_to
        FROM polities_periods_cliopatria
        GROUP BY polity_id
    )
    SELECT ic.wikidata_id, ic.name_en, ic.polity_name, pe.max_to
    FROM individuals_cliopatria ic
    LEFT JOIN polity_end pe ON pe.polity_id = ic.polity_id
    WHERE ic.polity_name IS NOT NULL
      AND ic.floruit_period_start IS NULL
      AND {clause}
      AND EXISTS (
          SELECT 1 FROM wikimedia_links wl
          WHERE wl.wikidata_id = ic.wikidata_id
            AND wl.site LIKE '%.wikipedia.org'
      )
    ORDER BY RANDOM()
    LIMIT ?;
    """
    cur = conn.execute(sql, (PAST_POLITY_CUTOFF, n))
    return [
        {
            "wikidata_id": r[0],
            "name": r[1],
            "polity": r[2],
            "polity_max_to_year": r[3],
            "era": era,
        }
        for r in cur.fetchall()
    ]


def pick_sample(conn: sqlite3.Connection, n: int) -> list[dict]:
    """Stratified sample: half from past polities (pre-1800), half from modern polities."""
    half = n // 2
    past = _query_sample(conn, half, "past")
    modern = _query_sample(conn, n - half, "modern")
    sample = past + modern
    random.shuffle(sample)
    return sample


def pick_wikipedia_link(conn: sqlite3.Connection, wikidata_id: str) -> dict | None:
    """English Wikipedia link if present, else a random non-English Wikipedia link."""
    rows = conn.execute(
        "SELECT site, title, url FROM wikimedia_links "
        "WHERE wikidata_id = ? AND site LIKE '%.wikipedia.org'",
        (wikidata_id,),
    ).fetchall()
    if not rows:
        return None
    en = [r for r in rows if r[0] == "en.wikipedia.org"]
    chosen = en[0] if en else random.choice(rows)
    return {"site": chosen[0], "title": chosen[1], "url": chosen[2]}


# ---------------------------------------------------------------------------
# Step 2: fetch Wikipedia extract
# ---------------------------------------------------------------------------


def fetch_wikipedia_extract(site: str, title: str) -> str:
    """Plain-text extract of the article (no HTML, no section limit)."""
    api = f"https://{site}/w/api.php"
    params = {
        "action": "query",
        "prop": "extracts",
        "explaintext": 1,
        "redirects": 1,
        "format": "json",
        "titles": title,
    }
    headers = {"User-Agent": "cultura-database-test/1.0 (cdedampierre@bunka.ai)"}
    resp = requests.get(api, params=params, headers=headers, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})
    for _pid, page in pages.items():
        extract = page.get("extract") or ""
        if extract:
            return extract[:WIKI_EXTRACT_CHARS]
    return ""


# ---------------------------------------------------------------------------
# Step 3: Gemini extraction via OpenRouter
# ---------------------------------------------------------------------------


def call_gemini(api_key: str, person: dict, article: str) -> dict:
    user_msg = (
        f"Person name: {person['name']}\n"
        f"Polity (context): {person['polity']}\n"
        f"Wikipedia language: {person['wikipedia_lang']}\n\n"
        f"--- ARTICLE TEXT ---\n{article}\n--- END ARTICLE ---\n\n"
        "Extract the floruit period. Respond with JSON only."
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
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://bunka.ai/",
        "X-Title": "Cultura floruit extraction test",
    }

    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.post(
                OPENROUTER_URL, headers=headers, json=body, timeout=LLM_TIMEOUT
            )
            if r.status_code in (408, 409, 425, 429, 500, 502, 503, 504):
                time.sleep(1.5 * (2**attempt))
                last_exc = requests.HTTPError(f"{r.status_code} {r.reason}")
                continue
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            usage = data.get("usage", {}) or {}
            return {
                "extraction": parsed,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "cost_usd": usage.get("cost"),
            }
        except (
            requests.RequestException,
            ValueError,
            KeyError,
            json.JSONDecodeError,
        ) as e:
            last_exc = e
            time.sleep(1.5 * (2**attempt))
    raise last_exc if last_exc else RuntimeError("call_gemini: unknown error")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    random.seed(RANDOM_SEED)
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("OPEN_ROUTER_API")
    if not api_key:
        log("ERROR: OPEN_ROUTER_API not set in .env")
        return 1
    db_path = DEFAULT_DB
    if not db_path.exists():
        log(f"ERROR: database not found at {db_path}")
        return 1

    log(f"DB    : {db_path}")
    log(f"Model : {MODEL}")
    log(f"Sample: {SAMPLE_SIZE}")
    log(f"Workers: {NUM_WORKERS} (threads — work is HTTP-bound)")
    log("Estimated runtime: ~1-2 minutes with parallelism.")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = OUT_DIR / f"floruit_extraction_test_{ts}.csv"
    md_path = OUT_DIR / f"floruit_extraction_test_cost_{ts}.md"

    # One sqlite connection per thread (sqlite3 connections are not thread-safe by default).
    tls = threading.local()

    def get_conn() -> sqlite3.Connection:
        if not hasattr(tls, "conn"):
            tls.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        return tls.conn

    sample = pick_sample(get_conn(), SAMPLE_SIZE)
    log(f"Selected {len(sample)} individuals")

    fieldnames = [
        "wikidata_id",
        "name",
        "polity",
        "era",
        "polity_max_to_year",
        "wikipedia_lang",
        "wikipedia_title",
        "wikipedia_url",
        "article_chars",
        "floruit_period_start",
        "floruit_period_end",
        "reasoning",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cost_usd",
        "error",
    ]

    totals_lock = threading.Lock()
    totals = {"prompt": 0, "completion": 0, "cost": 0.0, "ok": 0, "fail": 0}

    def process_one(person: dict) -> dict:
        """Build one CSV row. Runs inside a worker thread."""
        row = {k: "" for k in fieldnames}
        row["wikidata_id"] = person["wikidata_id"]
        row["name"] = person["name"]
        row["polity"] = person["polity"]
        row["era"] = person.get("era")
        row["polity_max_to_year"] = person.get("polity_max_to_year")
        try:
            link = pick_wikipedia_link(get_conn(), person["wikidata_id"])
            if not link:
                row["error"] = "no wikipedia link"
                with totals_lock:
                    totals["fail"] += 1
                return row
            lang = link["site"].split(".")[0]
            row["wikipedia_lang"] = lang
            row["wikipedia_title"] = link["title"]
            row["wikipedia_url"] = link["url"]

            article = fetch_wikipedia_extract(link["site"], link["title"])
            row["article_chars"] = len(article)
            if not article:
                row["error"] = "empty wikipedia extract"
                with totals_lock:
                    totals["fail"] += 1
                return row

            result = call_gemini(api_key, {**person, "wikipedia_lang": lang}, article)
            ext = result["extraction"] or {}
            row["floruit_period_start"] = ext.get("floruit_period_start")
            row["floruit_period_end"] = ext.get("floruit_period_end")
            row["reasoning"] = ext.get("reasoning")
            row["prompt_tokens"] = result.get("prompt_tokens")
            row["completion_tokens"] = result.get("completion_tokens")
            row["total_tokens"] = result.get("total_tokens")
            row["cost_usd"] = result.get("cost_usd")

            with totals_lock:
                if isinstance(result.get("prompt_tokens"), int):
                    totals["prompt"] += result["prompt_tokens"]
                if isinstance(result.get("completion_tokens"), int):
                    totals["completion"] += result["completion_tokens"]
                if isinstance(result.get("cost_usd"), (int, float)):
                    totals["cost"] += float(result["cost_usd"])
                totals["ok"] += 1
        except Exception as e:
            row["error"] = f"{type(e).__name__}: {e}"
            with totals_lock:
                totals["fail"] += 1
        return row

    write_lock = threading.Lock()
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        with ThreadPoolExecutor(max_workers=NUM_WORKERS) as pool:
            futures = [pool.submit(process_one, p) for p in sample]
            for fut in tqdm(
                as_completed(futures),
                total=len(futures),
                desc="Extracting floruit",
                unit="person",
            ):
                row = fut.result()
                with write_lock:
                    writer.writerow(row)
                    f.flush()

    total_prompt = totals["prompt"]
    total_completion = totals["completion"]
    total_cost = totals["cost"]
    successes = totals["ok"]
    failures = totals["fail"]

    avg_cost = (total_cost / successes) if successes else 0.0
    md = (
        f"# Floruit extraction — cost log\n\n"
        f"- Run timestamp : `{ts}`\n"
        f"- Model         : `{MODEL}`\n"
        f"- Sample size   : {len(sample)}\n"
        f"- Workers       : {NUM_WORKERS} threads\n"
        f"- Successes     : {successes}\n"
        f"- Failures      : {failures}\n"
        f"- Prompt tokens : {total_prompt:,}\n"
        f"- Output tokens : {total_completion:,}\n"
        f"- **Total cost (USD)** : ${total_cost:.4f}\n"
        f"- Avg cost / person   : ${avg_cost:.5f}\n\n"
        f"Cost values come from OpenRouter's `usage.cost` field "
        f"(returned because the request was made with `usage: {{include: true}}`).\n\n"
        f"Output CSV: `{csv_path.name}`\n"
    )
    md_path.write_text(md, encoding="utf-8")

    log(f"CSV  -> {csv_path}")
    log(f"COST -> {md_path}")
    log(f"DONE: {successes} ok, {failures} failed, total cost ${total_cost:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
