"""
Test: extract any dates from Wikipedia for individuals who have NO date in
any source on the Wikidata side (after every recovery step) but DO have at
least one Wikipedia page.

Pipeline
--------
1. Sample SAMPLE_SIZE rows from data/individuals_no_date_with_wikipedia.csv.
2. Pick the Wikipedia URL already chosen there (English first, else any).
3. Fetch the plain-text extract via MediaWiki API.
4. Ask Gemini (via OpenRouter) to extract birth/death/floruit + any other
   dates with reasoning, returning strict JSON.
5. Write:
     - a CSV with one row per individual + token/cost columns
     - a Markdown cost-summary
     - a self-contained HTML annotation page where you mark each row
       Yes/No and download the verdicts as JSON.

Reuses the SYSTEM_PROMPT and OpenRouter wiring from
test_extract_floruit_from_wikipedia.py (the user-rewritten version).

Run
---
    .venv/bin/python scripts/test_extract_dates_from_wikipedia_no_date.py
"""

from __future__ import annotations

import csv
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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_CSV = PROJECT_ROOT / "data" / "individuals_no_date_with_wikipedia.csv"
LOCAL_CACHE_DIR = PROJECT_ROOT / "data" / "wikipedia_pages_missing_dates"
OUT_DIR = Path(__file__).resolve().parent
ANNOTATION_DIR = PROJECT_ROOT / "annotations"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "google/gemini-2.5-flash-lite"

SAMPLE_SIZE = 22000
WIKI_EXTRACT_CHARS = 4000
HTTP_TIMEOUT = 60
LLM_TIMEOUT = 120
MAX_RETRIES = 3
RANDOM_SEED = 50
NUM_WORKERS = 16

SYSTEM_PROMPT = """You are an expert historian extracting biographical dates.

Given an English (or foreign-language) Wikipedia article about a person,
extract the following information ONLY when it is explicitly stated in
the article:
 - Birthdate
 - DeathDate
 - Floruit_date — the years during which the person was active in their
   primary occupation (career, public life, scholarly work, reign, etc.)
 - Dates — additional years from events the INDIVIDUAL personally
   participated in DURING THEIR LIFETIME (works they published, offices
   they held, battles they fought, awards they received, marriages,
   education, appointments, relocations, etc.).

==============================================================
CRITICAL RULES (from recent annotation feedback — read carefully)
==============================================================

A. STATED, NOT INFERRED.
   Every date you return must be present in the article text (in the
   prose, an infobox, a category, a dated section header, etc.).
   Do NOT invent a Floruit_date.start by guessing when a career
   "probably" began. Do NOT extrapolate from phrases like "in her
   teenage years", "in recent years", "since the early days", or
   future plans. If you cannot point to the exact year in the text,
   do NOT emit it.

B. SINGLE-DATE FLORUIT.
   If only ONE active-life year is mentioned, set
     Floruit_date.start = that year
     Floruit_date.end   = null
   Do NOT duplicate the same year as both start and end
   (i.e. NEVER return 1898–1898).

C. CENTURY-LEVEL FLORUIT IS ACCEPTABLE.
   If the article only places the person in a century (e.g. "18th
   century scholar", "fl. 12th century"), still emit the floruit.
   Use the canonical bucket bounds:
     18th century → start=1701, end=1800
     12th century → start=1101, end=1200
     5th century BCE → start=-500, end=-401
   AND set `precision`: "century". The `precision` field MUST be
   "century" — never label a century-level inference as "year"
   precision. The same applies to "decade" and "millennium".

D. PRESERVE THE STATED GRANULARITY.
   If the article literally says "18th century", return
   precision="century"; do NOT silently rewrite it into a year-precision
   1700–1799 range. The precision tag is what conveys the bucket.

E. STATED ANCHOR DATES COUNT.
   If the article gives stated years that anchor the individual's
   career (e.g. "played in the club's 2004 season", "served under
   President X 2010-2015"), include them — both in `Dates` and as
   evidence for Floruit_date. Do NOT return all-null when stated
   year anchors exist in the text. Stated years tied to the
   individual are extraction targets, even if the article does not
   spell out "X was active from Y to Z".

==============================================================

Return JSON with EXACTLY this shape. `precision` is ALWAYS one of the
strings "year", "decade", "century", "millennium", or null — never a
combination, never an ordinal like "15th".

{
  "Birthdate":    { "year": <int or null>, "precision": "year"|"decade"|"century"|"millennium"|null },
  "DeathDate":    { "year": <int or null>, "precision": "year"|"decade"|"century"|"millennium"|null },
  "Floruit_date": { "start": <int or null>, "end": <int or null>, "precision": "year"|"decade"|"century"|"millennium"|null },
  "Dates":        [ { "year": <int>, "label": "<what it refers to>" }, ... ]
}

Worked example — Leonardo da Vinci (year-precision):
{
  "Birthdate":    { "year": 1452, "precision": "year" },
  "DeathDate":    { "year": 1519, "precision": "year" },
  "Floruit_date": { "start": 1472, "end": 1519, "precision": "year" },
  "Dates": [
    { "year": 1472, "label": "admitted to the Florentine painters' guild" },
    { "year": 1482, "label": "moved to Milan to serve Ludovico Sforza" },
    { "year": 1503, "label": "began the Mona Lisa" },
    { "year": 1516, "label": "moved to France at the invitation of Francis I" }
  ]
}

Worked example — century-only article (rule C/D):
{
  "Birthdate":    { "year": null, "precision": null },
  "DeathDate":    { "year": null, "precision": null },
  "Floruit_date": { "start": 1701, "end": 1800, "precision": "century" },
  "Dates": []
}

Worked example — single-year activity (rule B):
{
  "Birthdate":    { "year": null, "precision": null },
  "DeathDate":    { "year": null, "precision": null },
  "Floruit_date": { "start": 1898, "end": null, "precision": "year" },
  "Dates": [
    { "year": 1898, "label": "ranked 69th in the Guangxu Wuxu imperial examination" },
    { "year": 1898, "label": "assigned as a county magistrate" }
  ]
}

INCLUSION RULES — a date belongs in `Dates` only if ALL three hold:
1. It is a SPECIFIC YEAR (4-digit integer, or negative for BCE). Never
   extract a day-of-month or month-of-year as a year. Century-only
   information (e.g. "14th century") goes into Floruit_date with
   precision="century", NOT into the Dates list.
2. The event directly involves THE INDIVIDUAL as participant, agent,
   author, honoree, or subject — not events about institutions, places,
   ancestors, descendants, colleagues, or general historical context.
3. The year falls within the individual's lifetime (between Birthdate
   and DeathDate when known; otherwise plausibly within their active
   life).

Reject (do NOT add to `Dates`) — common pitfalls:
- "commemorated on August 30" → "30" is a calendar day, NOT year 30 / -30.
- "retrieved 2020", "accessed 2024-01", "archive date 2023" → source-metadata.
- Article publication / "as of" / last-updated timestamps from the
  Wikipedia text itself.
- Events BEFORE the person was born (founding of an institution they
  later joined, prior history of a town/diocese/title).
- Events AFTER the person died (descendant deaths, posthumous
  destruction, later commemorations).
- Achievements of OTHER named people mentioned in the article.
- Awards / honors / activities of relatives, students, employer, or
  organisation that don't directly involve the individual.

Birthdate / DeathDate guards:
- A "birth year" you can't reconcile with the floruit (e.g. floruit
  starts in 1788 but you read birth=1955) is almost certainly NOT a
  birth date — most likely a citation/edit/retrieval year. Drop it.
- A "death year" in the future (after the article's apparent writing
  date) is almost certainly NOT a death date — drop it.
- Before returning null for Birthdate, scan the article for explicit
  birth cues: "born <year>", "(<year>–", "b. <year>", parenthetical
  (1942–), infobox birth fields, or non-English equivalents (né,
  geboren, 生, nacido, родился).

Other rules
- Use NEGATIVE integers for BCE years (e.g. -44 for 44 BCE). Years are
  integers, never ISO strings.
- If the article is too sparse to infer anything reliable, set the date
  fields to null.
- Output JSON ONLY. No prose around it. No extra top-level fields.
"""


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Step 1: pick the sample from the no-date CSV
# ---------------------------------------------------------------------------


def build_local_cache_index() -> dict[str, Path]:
    """Walk LOCAL_CACHE_DIR once and return {wikidata_id: path} for every
    JSON whose `char_count` > 0. Skips empty stubs and `.error.json` files.
    """
    index: dict[str, Path] = {}
    if not LOCAL_CACHE_DIR.exists():
        return index
    for shard in LOCAL_CACHE_DIR.iterdir():
        if not shard.is_dir():
            continue
        for f in shard.iterdir():
            if "error" in f.name or f.suffix != ".json":
                continue
            try:
                d = json.loads(f.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if (d.get("char_count") or 0) > 0 and (d.get("extract") or "").strip():
                index[d["wikidata_id"]] = f
    return index


def pick_sample(csv_path: Path, n: int, cache_index: dict[str, Path]) -> list[dict]:
    """Random sample of n rows whose QID has a non-empty cached extract."""
    pool: list[dict] = []
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            qid = row["wikidata_id"]
            if qid not in cache_index:
                continue
            url = row.get("any_wikipedia_url") or row.get("en_wikipedia_url") or ""
            pool.append(
                {
                    "wikidata_id": qid,
                    "name": row.get("name_en") or "",
                    "description": (row.get("description_en") or "").strip(),
                    "occupations": row.get("occupations_en") or "",
                    "country": row.get("country_of_citizenship_en") or "",
                    "wp_url": url,
                    "wp_lang": url.split("//", 1)[-1].split(".", 1)[0]
                    if url
                    else "",
                    "wp_title": url.rsplit("/wiki/", 1)[-1].replace("_", " ")
                    if url
                    else "",
                    "wp_pages_count": int(row.get("wikipedia_pages_count") or 0),
                    "_cache_path": cache_index[qid],
                }
            )
    rng = random.Random(RANDOM_SEED)
    rng.shuffle(pool)
    return pool[:n]


# ---------------------------------------------------------------------------
# Step 2: read Wikipedia extract from local cache
# ---------------------------------------------------------------------------

from urllib.parse import unquote  # noqa: E402  (kept for downstream callers)


def read_local_extract(cache_path: Path) -> str:
    """Read the cached MediaWiki extract for one QID and cap to
    WIKI_EXTRACT_CHARS. Returns "" on any error (treated by caller as
    'empty extract')."""
    try:
        d = json.loads(cache_path.read_text())
    except (OSError, json.JSONDecodeError):
        return ""
    extract = (d.get("extract") or "").strip()
    return extract[:WIKI_EXTRACT_CHARS]


# ---------------------------------------------------------------------------
# Step 3: Gemini extraction via OpenRouter
# ---------------------------------------------------------------------------


def call_gemini(api_key: str, person: dict, article: str) -> dict:
    user_msg = (
        f"Person name: {person['name']}\n"
        f"Wikidata description: {person.get('description') or '(none)'}\n"
        f"Wikipedia language: {person['wp_lang']}\n\n"
        f"--- ARTICLE TEXT ---\n{article}\n--- END ARTICLE ---\n\n"
        "Extract the dates. Respond with JSON only."
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
        "X-Title": "Cultura date-recovery test (no-date set)",
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
# Step 4: HTML annotation page
# ---------------------------------------------------------------------------

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Date recovery review — {N} individuals</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Crect x='2' y='6' width='3' height='8' fill='%232b6cb0'/%3E%3Crect x='6' y='3' width='4' height='11' fill='%232b6cb0'/%3E%3Crect x='11' y='8' width='3' height='6' fill='%232b6cb0'/%3E%3C/svg%3E">
<style>
  :root {{
    --bg:#fafafa; --card:#fff; --line:#e5e5e5; --ink:#1a1a1a; --muted:#666;
    --ok:#0f9d58; --bad:#d93025; --hl:#2b6cb0;
  }}
  * {{ box-sizing:border-box; }}
  html, body {{ margin:0; padding:0; }}
  body {{ font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; background:var(--bg); color:var(--ink); }}
  header {{ position:sticky; top:0; z-index:10; background:#fff; border-bottom:1px solid var(--line);
            padding:14px 22px; display:flex; align-items:center; gap:20px; flex-wrap:wrap; }}
  header h1 {{ margin:0; font-size:16px; font-weight:600; }}
  header .meta {{ color:var(--muted); font-size:12px; }}
  .counters {{ display:flex; gap:14px; font-size:12px; color:var(--muted); }}
  .counters b {{ color:var(--ink); }}
  button {{ font:inherit; cursor:pointer; border:1px solid var(--line); background:#fff; padding:6px 12px; border-radius:6px; }}
  button:hover {{ background:#f3f3f3; }}
  .primary {{ background:var(--hl); color:#fff; border-color:var(--hl); }}
  main {{ padding:18px 22px 80px; max-width:1180px; margin:0 auto; }}
  .row {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
          padding:14px 16px; margin-bottom:10px;
          display:grid; grid-template-columns:42px 1fr 380px 180px; gap:14px; align-items:start; }}
  .row.annotated.correct {{ border-color:#b6dfc1; background:#f7fcf9; }}
  .row.annotated.wrong   {{ border-color:#f3b7b0; background:#fdf6f5; }}
  .idx {{ color:var(--muted); font-variant-numeric:tabular-nums; padding-top:2px; }}
  .name {{ font-weight:600; }}
  .name a {{ color:var(--ink); text-decoration:none; }}
  .name a:hover {{ color:var(--hl); text-decoration:underline; }}
  .desc {{ color:var(--muted); font-size:12px; margin-top:2px; }}
  .tags {{ margin-top:6px; display:flex; flex-wrap:wrap; gap:4px; }}
  .chip {{ border:1px solid var(--line); border-radius:12px; padding:2px 8px; font-size:11px; color:var(--muted); }}
  .links a {{ color:var(--hl); text-decoration:none; font-size:12px; margin-right:8px; }}
  .links a:hover {{ text-decoration:underline; }}
  .extract {{ margin-top:8px; font-size:12.5px; line-height:1.5; color:#333;
              max-height:160px; overflow:auto; padding:8px 10px; background:#fafafa;
              border:1px solid var(--line); border-radius:6px; white-space:pre-wrap; }}
  .stats {{ display:grid; grid-template-columns:1fr 1fr 1.4fr; gap:6px; }}
  .stat {{
    background:#f7f8fa; border:1px solid var(--line); border-radius:8px;
    padding:7px 9px; min-width:0;
  }}
  .stat .stat-label {{
    font-size:10px; font-weight:700; text-transform:uppercase;
    letter-spacing:0.6px; color:var(--muted); margin-bottom:2px;
  }}
  .stat .stat-year {{
    font-size:17px; font-variant-numeric:tabular-nums; font-weight:600;
    color:var(--ink); line-height:1.15;
  }}
  .stat .stat-year.empty {{ color:#c4c4c4; font-weight:400; font-size:14px; }}
  .stat .stat-prec {{ font-size:10.5px; color:var(--muted); margin-top:2px; }}
  .stat-floruit {{ background:#f0f5fb; border-color:#d4e2f3; }}

  .dates-block {{ margin-top:10px; }}
  .dates-header {{
    font-size:10px; font-weight:700; text-transform:uppercase;
    letter-spacing:0.6px; color:var(--muted);
    padding-bottom:4px; margin-bottom:6px; border-bottom:1px solid var(--line);
    display:flex; justify-content:space-between; align-items:baseline;
  }}
  .dates-header .count {{ color:var(--hl); font-size:11px; }}
  .dates-list {{ list-style:none; margin:0; padding:0;
                 max-height:180px; overflow:auto;
                 display:flex; flex-direction:column; gap:3px; }}
  .dates-list li {{ display:flex; gap:10px; font-size:12.5px;
                    padding:3px 4px; align-items:baseline;
                    border-radius:4px; }}
  .dates-list li:hover {{ background:#f6f8fb; }}
  .d-year {{ font-variant-numeric:tabular-nums; font-weight:600;
             color:var(--hl); min-width:54px; text-align:right; flex-shrink:0; }}
  .d-label {{ color:#444; flex:1; line-height:1.35; }}
  .dates-empty {{ color:#999; font-style:italic; font-size:12px; padding:4px 0; }}

  .reasoning {{
    margin-top:10px; padding:8px 10px;
    background:#fffbeb; border:1px solid #f3e7c0; border-radius:6px;
    font-size:12.5px; color:#333; line-height:1.5;
  }}
  .reasoning .label {{
    display:block; font-size:10.5px; color:#9c7800; font-weight:700;
    text-transform:uppercase; letter-spacing:0.5px; margin-bottom:4px;
  }}
  .reasoning.empty {{ background:#f6f6f6; border-color:#e5e5e5; color:#888; font-style:italic; }}
  .actions {{ display:flex; flex-direction:column; gap:6px; align-items:stretch; }}
  .actions .row-buttons {{ display:flex; gap:6px; }}
  .btn-yes,.btn-no {{ flex:1; padding:6px 0; text-align:center; border-radius:6px; border:1px solid var(--line); }}
  .row.annotated.correct .btn-yes {{ background:var(--ok); color:#fff; border-color:var(--ok); }}
  .row.annotated.wrong   .btn-no  {{ background:var(--bad); color:#fff; border-color:var(--bad); }}
  .note {{ width:100%; min-height:60px; font:inherit; padding:6px 8px;
           border:1px solid var(--line); border-radius:6px; resize:vertical; }}
  footer {{ position:fixed; left:0; right:0; bottom:0; background:#fff; border-top:1px solid var(--line);
            padding:10px 22px; display:flex; gap:14px; align-items:center; justify-content:space-between;
            font-size:12px; color:var(--muted); }}
</style>
</head>
<body>

<header>
  <h1>Date recovery review — no-date individuals</h1>
  <span class="meta">{N} rows · Gemini {MODEL} · random sample · seed {SEED}</span>
  <div class="counters">
    <span><b id="cnt-yes">0</b> correct</span>
    <span><b id="cnt-no">0</b> wrong</span>
    <span><b id="cnt-pending">{N}</b> pending</span>
  </div>
  <button id="export" class="primary">Download annotations</button>
</header>

<main id="rows"></main>

<footer>
  <span>Annotations are saved to your browser (localStorage). Click <b>Download annotations</b> for JSON.</span>
  <span><kbd>y</kbd>/<kbd>n</kbd> on the focused row</span>
</footer>

<script>
const DATA = {DATA_JSON};
const STORAGE_KEY = 'no_date_review_v1';
const state = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{{}}');

function fmt(v) {{ if (v === null || v === undefined || v === '') return '—'; return String(v); }}

function render() {{
  const main = document.getElementById('rows');
  main.innerHTML = '';
  let yes=0, no=0, pending=0;

  DATA.forEach((d, i) => {{
    const v = state[d.wikidata_id]?.verdict;
    const note = state[d.wikidata_id]?.note || '';
    if (v === 'yes') yes++; else if (v === 'no') no++; else pending++;

    const row = document.createElement('div');
    row.className = 'row' + (v ? ' annotated ' + (v === 'yes' ? 'correct' : 'wrong') : '');
    row.dataset.qid = d.wikidata_id;
    row.tabIndex = 0;

    const datesItems = (d.other_dates && d.other_dates.length)
      ? d.other_dates.map(o => `<li><span class="d-year">${{o.year ?? '—'}}</span><span class="d-label">${{(o.label||'(no label)').replace(/</g,'&lt;')}}</span></li>`).join('')
      : '';
    const datesBlock = (d.other_dates && d.other_dates.length)
      ? `<div class="dates-block">
           <div class="dates-header"><span>Other dates</span><span class="count">${{d.other_dates.length}}</span></div>
           <ul class="dates-list">${{datesItems}}</ul>
         </div>`
      : `<div class="dates-block">
           <div class="dates-header"><span>Other dates</span><span class="count">0</span></div>
           <div class="dates-empty">No other dates extracted.</div>
         </div>`;
    const fmtYear = (y, p) => {{
      if (y === null || y === undefined || y === '') return `<div class="stat-year empty">—</div>`;
      const prec = p ? `<div class="stat-prec">${{p}}</div>` : '';
      return `<div class="stat-year">${{y}}</div>${{prec}}`;
    }};
    const fmtFloruit = (s, e, p) => {{
      const hasS = s !== null && s !== undefined && s !== '';
      const hasE = e !== null && e !== undefined && e !== '';
      if (!hasS && !hasE) return `<div class="stat-year empty">—</div>`;
      const range = hasS && hasE ? `${{s}} – ${{e}}` : (hasS ? `${{s}}` : `${{e}}`);
      const prec = p ? `<div class="stat-prec">${{p}}</div>` : '';
      return `<div class="stat-year">${{range}}</div>${{prec}}`;
    }};

    row.innerHTML = `
      <div class="idx">${{i+1}}</div>
      <div>
        <div class="name">
          <a href="https://www.wikidata.org/wiki/${{d.wikidata_id}}" target="_blank">${{fmt(d.name)}}</a>
        </div>
        ${{d.description ? `<div class="desc">${{d.description}}</div>` : ''}}
        <div class="tags">
          <span class="chip">${{d.wp_lang}}.wikipedia</span>
          ${{d.country ? `<span class="chip">${{d.country}}</span>` : ''}}
          ${{d.occupations ? `<span class="chip">${{d.occupations.split(';').slice(0,3).join(' · ')}}</span>` : ''}}
          <span class="chip">${{d.wikidata_id}}</span>
        </div>
        <div class="links" style="margin-top:6px;">
          <a href="${{d.wp_url}}" target="_blank">Wikipedia (${{d.wp_lang}})</a>
          <a href="https://www.wikidata.org/wiki/${{d.wikidata_id}}" target="_blank">Wikidata</a>
          <a href="https://www.google.com/search?q=${{encodeURIComponent((d.name||'') + ' ' + (d.description||''))}}" target="_blank">Google</a>
        </div>
        <div class="extract">${{(d.lead_extract || '').replace(/</g,'&lt;')}}</div>
      </div>
      <div>
        <div class="stats">
          <div class="stat">
            <div class="stat-label">Birth</div>
            ${{fmtYear(d.birthdate, d.birthdate_precision)}}
          </div>
          <div class="stat">
            <div class="stat-label">Death</div>
            ${{fmtYear(d.deathdate, d.deathdate_precision)}}
          </div>
          <div class="stat stat-floruit">
            <div class="stat-label">Floruit</div>
            ${{fmtFloruit(d.floruit_period_start, d.floruit_period_end, d.floruit_precision)}}
          </div>
        </div>
        ${{datesBlock}}
        <div class="reasoning${{d.reasoning ? '' : ' empty'}}">
          <span class="label">AI reasoning</span>${{(d.reasoning || 'No reasoning returned by the model.').replace(/</g,'&lt;')}}
        </div>
      </div>
      <div class="actions">
        <div class="row-buttons">
          <button class="btn-yes" data-verdict="yes" title="Correct (y)">Yes</button>
          <button class="btn-no"  data-verdict="no"  title="Wrong (n)">No</button>
        </div>
        <textarea class="note" placeholder="Note / corrected dates">${{note.replace(/</g,'&lt;')}}</textarea>
      </div>`;

    row.querySelectorAll('button').forEach(btn => {{
      btn.addEventListener('click', () => mark(d.wikidata_id, btn.dataset.verdict));
    }});
    row.querySelector('.note').addEventListener('change', e => {{
      state[d.wikidata_id] = state[d.wikidata_id] || {{}};
      state[d.wikidata_id].note = e.target.value;
      persist();
    }});
    main.appendChild(row);
  }});

  document.getElementById('cnt-yes').textContent = yes;
  document.getElementById('cnt-no').textContent  = no;
  document.getElementById('cnt-pending').textContent = pending;
}}

function mark(qid, verdict) {{
  const cur = state[qid] || {{}};
  if (cur.verdict === verdict) delete cur.verdict; else cur.verdict = verdict;
  state[qid] = cur; persist(); render();
}}

function persist() {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }}

document.getElementById('export').addEventListener('click', () => {{
  const out = DATA.map(d => ({{
    wikidata_id: d.wikidata_id, name: d.name,
    birthdate: d.birthdate, deathdate: d.deathdate,
    floruit_period_start: d.floruit_period_start, floruit_period_end: d.floruit_period_end,
    other_dates: d.other_dates,
    verdict: state[d.wikidata_id]?.verdict || null,
    note:    state[d.wikidata_id]?.note    || '',
  }}));
  const blob = new Blob([JSON.stringify(out, null, 2)], {{type:'application/json'}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'no_date_review_annotations.json'; a.click();
  URL.revokeObjectURL(url);
}});

document.addEventListener('keydown', e => {{
  if (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'INPUT') return;
  const focused = document.activeElement;
  if (!focused || !focused.classList.contains('row')) return;
  const qid = focused.dataset.qid;
  if (e.key === 'y') mark(qid, 'yes');
  else if (e.key === 'n') mark(qid, 'no');
}});

render();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("OPEN_ROUTER_API")
    if not api_key:
        log("ERROR: OPEN_ROUTER_API not set in .env")
        return 1
    if not INPUT_CSV.exists():
        log(f"ERROR: input CSV not found at {INPUT_CSV}")
        return 1

    log(f"Input  : {INPUT_CSV}")
    log(f"Cache  : {LOCAL_CACHE_DIR}")
    log(f"Model  : {MODEL}")
    log(f"Sample : {SAMPLE_SIZE}")
    log(f"Workers: {NUM_WORKERS} threads")
    log("Estimated runtime: ~55 min (entire populated cache ≈21,357 rows, 16 threads, local cache, no reasoning).")

    log("Indexing local Wikipedia cache (only QIDs with non-empty extracts)...")
    cache_index = build_local_cache_index()
    log(f"  cache hits: {len(cache_index):,} populated QIDs")

    sample = pick_sample(INPUT_CSV, SAMPLE_SIZE, cache_index)
    log(f"Selected {len(sample)} individuals (all from local cache, no Wikipedia API calls)")
    if len(sample) < SAMPLE_SIZE:
        log(
            f"WARNING: only {len(sample)} populated cache entries match the input CSV — "
            f"requested {SAMPLE_SIZE}. Continuing with what we have."
        )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = OUT_DIR / f"no_date_extraction_test_{ts}.csv"
    md_path = OUT_DIR / f"no_date_extraction_cost_{ts}.md"
    ANNOTATION_DIR.mkdir(exist_ok=True)
    # The HTML always lives at the same path so re-running the script just
    # overwrites the previous review page (no timestamped HTMLs piling up).
    html_path = ANNOTATION_DIR / "no_date_extraction_review.html"

    fieldnames = [
        "wikidata_id",
        "name",
        "description",
        "country",
        "occupations",
        "wp_lang",
        "wp_title",
        "wp_url",
        "article_chars",
        "birthdate",
        "birthdate_precision",
        "deathdate",
        "deathdate_precision",
        "floruit_period_start",
        "floruit_period_end",
        "floruit_precision",
        "other_dates_json",
        "reasoning",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cost_usd",
        "error",
    ]

    totals_lock = threading.Lock()
    totals = {"prompt": 0, "completion": 0, "cost": 0.0, "ok": 0, "fail": 0}
    cards: list[dict] = []
    cards_lock = threading.Lock()

    def process_one(person: dict) -> dict:
        row = {k: "" for k in fieldnames}
        row.update(
            {
                "wikidata_id": person["wikidata_id"],
                "name": person["name"],
                "description": person["description"],
                "country": person["country"],
                "occupations": person["occupations"],
                "wp_lang": person["wp_lang"],
                "wp_title": person["wp_title"],
                "wp_url": person["wp_url"],
            }
        )
        card = {
            "wikidata_id": person["wikidata_id"],
            "name": person["name"],
            "description": person["description"],
            "country": person["country"],
            "occupations": person["occupations"],
            "wp_lang": person["wp_lang"],
            "wp_url": person["wp_url"],
            "lead_extract": "",
            "birthdate": None,
            "birthdate_precision": None,
            "deathdate": None,
            "deathdate_precision": None,
            "floruit_period_start": None,
            "floruit_period_end": None,
            "floruit_precision": None,
            "other_dates": [],
            "reasoning": "",
        }
        try:
            article = read_local_extract(person["_cache_path"])
            row["article_chars"] = len(article)
            card["lead_extract"] = article[:1500]
            if not article:
                row["error"] = "empty wikipedia extract"
                with totals_lock:
                    totals["fail"] += 1
                with cards_lock:
                    cards.append(card)
                return row

            result = call_gemini(api_key, person, article)
            ext = result["extraction"] or {}

            # Case-insensitive lookup of a top-level key with several aliases.
            lower_ext = (
                {k.lower(): v for k, v in ext.items()} if isinstance(ext, dict) else {}
            )

            def pick(*keys):
                for k in keys:
                    v = lower_ext.get(k.lower())
                    if v not in (None, "", []):
                        return v
                return None

            def unwrap_date(obj, year_keys=("year",)):
                """Return (year, precision) from either a nested {year, precision}
                dict or a bare int/string."""
                if isinstance(obj, dict):
                    y = None
                    for k in year_keys:
                        if k in obj and obj[k] not in (None, ""):
                            y = obj[k]
                            break
                    p = obj.get("precision")
                    return y, p
                return obj, None

            # New nested schema (Birthdate/DeathDate/Floruit_date/Dates) + legacy fallback.
            birth_obj = pick(
                "Birthdate", "birthdate", "birthdayte", "birth_date", "birth"
            )
            death_obj = pick("DeathDate", "deathdate", "death_date", "death")
            fl_obj = pick("Floruit_date", "floruit_date", "floruit")
            other = pick("Dates", "other_dates", "any_dates", "dates") or []
            reas = pick("reasoning") or ""

            birth, b_pr = unwrap_date(birth_obj)
            death, d_pr = unwrap_date(death_obj)
            if isinstance(fl_obj, dict):
                fl_s = fl_obj.get("start")
                fl_e = fl_obj.get("end")
                fl_pr = fl_obj.get("precision")
            elif isinstance(fl_obj, list) and len(fl_obj) >= 1:
                fl_s = fl_obj[0]
                fl_e = fl_obj[1] if len(fl_obj) > 1 else None
                fl_pr = None
            else:
                fl_s, fl_e, fl_pr = fl_obj, None, None

            # Legacy flat-schema fallback for the precision/range fields.
            if b_pr is None:
                b_pr = pick("birthdate_precision", "birth_precision")
            if d_pr is None:
                d_pr = pick("deathdate_precision", "death_precision")
            if fl_pr is None:
                fl_pr = pick("floruit_precision")
            if fl_s is None:
                fl_s = pick("floruit_period_start", "floruit_start", "flrout_start")
            if fl_e is None:
                fl_e = pick("floruit_period_end", "floruit_end")

            row["birthdate"] = birth
            row["birthdate_precision"] = b_pr
            row["deathdate"] = death
            row["deathdate_precision"] = d_pr
            row["floruit_period_start"] = fl_s
            row["floruit_period_end"] = fl_e
            row["floruit_precision"] = fl_pr
            row["other_dates_json"] = json.dumps(other, ensure_ascii=False)
            row["reasoning"] = reas
            row["prompt_tokens"] = result.get("prompt_tokens")
            row["completion_tokens"] = result.get("completion_tokens")
            row["total_tokens"] = result.get("total_tokens")
            row["cost_usd"] = result.get("cost_usd")

            card.update(
                {
                    "birthdate": birth,
                    "birthdate_precision": b_pr,
                    "deathdate": death,
                    "deathdate_precision": d_pr,
                    "floruit_period_start": fl_s,
                    "floruit_period_end": fl_e,
                    "floruit_precision": fl_pr,
                    "other_dates": other if isinstance(other, list) else [],
                    "reasoning": reas,
                }
            )
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
        with cards_lock:
            cards.append(card)
        return row

    write_lock = threading.Lock()
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        with ThreadPoolExecutor(max_workers=NUM_WORKERS) as pool:
            futures = [pool.submit(process_one, p) for p in sample]
            for fut in tqdm(
                as_completed(futures),
                total=len(futures),
                desc="Extracting dates",
                unit="person",
            ):
                with write_lock:
                    writer.writerow(fut.result())
                    f.flush()

    # cost summary
    avg_cost = (totals["cost"] / totals["ok"]) if totals["ok"] else 0.0
    md_path.write_text(
        f"# No-date Wikipedia date-recovery — cost log\n\n"
        f"- Run timestamp : `{ts}`\n"
        f"- Model         : `{MODEL}`\n"
        f"- Sample size   : {len(sample)}\n"
        f"- Successes     : {totals['ok']}\n"
        f"- Failures      : {totals['fail']}\n"
        f"- Prompt tokens : {totals['prompt']:,}\n"
        f"- Output tokens : {totals['completion']:,}\n"
        f"- **Total cost (USD)** : ${totals['cost']:.4f}\n"
        f"- Avg cost / person   : ${avg_cost:.5f}\n\n"
        f"CSV : `{csv_path.name}`\n"
        f"HTML: `{html_path.relative_to(PROJECT_ROOT)}`\n",
        encoding="utf-8",
    )

    # HTML — one card per row, in original sample order so the HTML matches the CSV.
    by_qid = {c["wikidata_id"]: c for c in cards}
    cards_in_order = [
        by_qid[p["wikidata_id"]] for p in sample if p["wikidata_id"] in by_qid
    ]
    html = HTML.format(
        N=len(cards_in_order),
        MODEL=MODEL,
        SEED=RANDOM_SEED,
        DATA_JSON=json.dumps(cards_in_order, ensure_ascii=False),
    )
    html_path.write_text(html, encoding="utf-8")

    log(f"CSV  -> {csv_path}")
    log(f"HTML -> {html_path}")
    log(f"COST -> {md_path}")
    log(
        f"DONE: {totals['ok']} ok, {totals['fail']} failed, total cost ${totals['cost']:.4f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
