"""
Extract dates and structured info from Wikipedia for the 487k individuals
with no date in any Wikidata-side source but at least one Wikipedia page.

Input  : data/individuals_no_date_with_wikipedia.csv
Output : data/individuals_no_date_wikipedia_extracts.csv

Strategy
--------
1. Pick the best Wikipedia page per individual (English first, else any language).
2. Group rows by wiki host (e.g. en.wikipedia.org, fr.wikipedia.org, ...).
3. Query the MediaWiki API in batches of 50 titles per host:
     prop=categories|extracts|info|pageprops
     - categories  -> "1452 births" / "1519 deaths" -> hard birth/death years
     - extracts    -> intro paragraph (plain text) for regex fallback
     - info        -> length, last-touched
4. Pull two date signals:
     a) categories regex   (most reliable; consistent across most language wikis)
     b) lead-paragraph regex for "(c. 1452 - 1519)", "(1452-1519)", "born 1452" etc.
5. Write one row per individual with everything we found.

This is rules-based, no LLM, no auth required. The MediaWiki API allows ~50
titles per request and ~200 req/s per IP without authentication; we cap at
8 concurrent host workers to stay well below that.

Run
---
    cd notebooks  &&  ../.venv/bin/python ../scripts/_one_off/extract_dates_from_wikipedia_for_no_date.py
or
    .venv/bin/python scripts/_one_off/extract_dates_from_wikipedia_for_no_date.py
"""

from __future__ import annotations

import csv
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import unquote

import requests
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_CSV = PROJECT_ROOT / "data" / "individuals_no_date_with_wikipedia.csv"
OUTPUT_CSV = PROJECT_ROOT / "data" / "individuals_no_date_wikipedia_extracts.csv"

USER_AGENT = "cultura_database/1.0 (research; cdedampierre@bunka.ai)"
BATCH_SIZE = 50  # MediaWiki hard cap for non-bots
N_WORKERS = 8  # parallel hosts
HTTP_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_SLEEP = 1.5

# ---------- regex patterns ------------------------------------------------

# "Category:1452 births" / "1452 births" / "Naissance en 1452" etc.
# We catch the simplest, most universal English pattern first. Most non-English
# wikis still use English categories on imported items, so this catches a lot.
RE_BIRTH_CAT = re.compile(r"\b(\d{1,4})\s*births?\b", re.I)
RE_DEATH_CAT = re.compile(r"\b(\d{1,4})\s*deaths?\b", re.I)
# French: "Naissance en 1452", "Décès en 1519"
RE_BIRTH_FR = re.compile(r"naissance\s+en\s+(\d{1,4})", re.I)
RE_DEATH_FR = re.compile(r"d[ée]c[èe]s\s+en\s+(\d{1,4})", re.I)
# Spanish: "Nacidos en 1452", "Fallecidos en 1519"
RE_BIRTH_ES = re.compile(r"nacidos?\s+en\s+(\d{1,4})", re.I)
RE_DEATH_ES = re.compile(r"fallecidos?\s+en\s+(\d{1,4})", re.I)
# Portuguese: "Nascidos em 1452", "Mortos em 1519"
RE_BIRTH_PT = re.compile(r"nascidos?\s+em\s+(\d{1,4})", re.I)
RE_DEATH_PT = re.compile(r"mortos?\s+em\s+(\d{1,4})", re.I)
# German: "Geboren 1452", "Gestorben 1519"
RE_BIRTH_DE = re.compile(r"geboren\s+(\d{1,4})", re.I)
RE_DEATH_DE = re.compile(r"gestorben\s+(\d{1,4})", re.I)
# Italian: "Nati nel 1452", "Morti nel 1519"
RE_BIRTH_IT = re.compile(r"nati\s+nel\s+(\d{1,4})", re.I)
RE_DEATH_IT = re.compile(r"morti\s+nel\s+(\d{1,4})", re.I)

BIRTH_PATTERNS = [
    RE_BIRTH_CAT,
    RE_BIRTH_FR,
    RE_BIRTH_ES,
    RE_BIRTH_PT,
    RE_BIRTH_DE,
    RE_BIRTH_IT,
]
DEATH_PATTERNS = [
    RE_DEATH_CAT,
    RE_DEATH_FR,
    RE_DEATH_ES,
    RE_DEATH_PT,
    RE_DEATH_DE,
    RE_DEATH_IT,
]

# Floruit / "active" categories: "Florida (XV century)", "11th-century mathematicians" ...
RE_CENTURY = re.compile(r"(\d{1,2})(?:st|nd|rd|th|er|ème|e)[\s-]+century", re.I)

# Inside-text date span: "(c. 1452 – 1519)", "(1452–1519)", "(1452 - 1519)"
RE_LIFE_SPAN = re.compile(
    r"\(\s*(?:c\.?\s*|circa\s*|ca\.\s*|um\s*|vers\s*)?"
    r"(\d{3,4})\s*(?:[-–—]|to)\s*"
    r"(?:c\.?\s*|circa\s*)?(\d{3,4})\s*(?:BC|BCE|AD|CE)?\s*\)",
    re.I,
)

RE_BORN = re.compile(r"\bborn\b[^.\n]{0,40}?(\d{3,4})", re.I)
RE_DIED = re.compile(r"\bdied\b[^.\n]{0,40}?(\d{3,4})", re.I)
RE_FL = re.compile(r"\b(?:fl\.?|floruit)\s*(\d{3,4})(?:\s*[-–]\s*(\d{3,4}))?", re.I)


def first_match(patterns, text):
    if not text:
        return None
    for p in patterns:
        m = p.search(text)
        if m:
            try:
                return int(m.group(1))
            except (ValueError, IndexError):
                continue
    return None


def title_from_url(url: str) -> str:
    """Pull the article title out of a Wikipedia URL."""
    return unquote(url.rsplit("/wiki/", 1)[-1]).replace("_", " ")


def host_from_url(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0]


# ---------- MediaWiki API call -------------------------------------------


def fetch_batch(session: requests.Session, host: str, titles: list[str]) -> dict:
    """One API request: up to 50 titles on one wiki. Returns {title: page_dict}."""
    params = {
        "action": "query",
        "format": "json",
        "formatversion": 2,
        "prop": "categories|extracts|info|pageprops",
        "titles": "|".join(titles),
        "cllimit": "max",
        "clshow": "!hidden",  # drop maintenance categories
        "exintro": 1,
        "explaintext": 1,
        "exlimit": "max",
        "inprop": "url",
        "redirects": 1,
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
            r.raise_for_status()
            data = r.json()
            return {p.get("title"): p for p in data.get("query", {}).get("pages", [])}
        except (requests.RequestException, ValueError) as e:
            if attempt == MAX_RETRIES - 1:
                tqdm.write(f"  [{host}] giving up on batch ({e})")
                return {}
            time.sleep(RETRY_SLEEP * (attempt + 1))
    return {}


def extract_one(page: dict) -> dict:
    """Pull dates + lead text from a MediaWiki page response."""
    if not page or page.get("missing"):
        return {"page_status": "missing"}

    cat_titles = " ; ".join(c.get("title", "") for c in page.get("categories", []))
    extract = page.get("extract", "") or ""

    birth_y = first_match(BIRTH_PATTERNS, cat_titles)
    death_y = first_match(DEATH_PATTERNS, cat_titles)

    span_m = RE_LIFE_SPAN.search(extract)
    span_birth = int(span_m.group(1)) if span_m else None
    span_death = int(span_m.group(2)) if span_m else None

    born_m = RE_BORN.search(extract)
    died_m = RE_DIED.search(extract)
    fl_m = RE_FL.search(extract)

    century_m = RE_CENTURY.search(cat_titles)

    return {
        "page_status": "ok",
        "page_length": page.get("length"),
        "lead_extract_chars": len(extract),
        "n_categories": len(page.get("categories", [])),
        "birth_year_from_cats": birth_y,
        "death_year_from_cats": death_y,
        "lead_lifespan_birth": span_birth,
        "lead_lifespan_death": span_death,
        "lead_born_year": int(born_m.group(1)) if born_m else None,
        "lead_died_year": int(died_m.group(1)) if died_m else None,
        "lead_floruit_start": int(fl_m.group(1)) if fl_m else None,
        "lead_floruit_end": int(fl_m.group(2)) if (fl_m and fl_m.group(2)) else None,
        "century_from_cats": int(century_m.group(1)) if century_m else None,
        "lead_extract": extract[:1000],  # cap to keep CSV manageable
    }


# ---------- per-host worker ----------------------------------------------


def process_host(host: str, rows: list[dict], pbar: tqdm) -> list[dict]:
    out = []
    session = requests.Session()
    for i in range(0, len(rows), BATCH_SIZE):
        chunk = rows[i : i + BATCH_SIZE]
        title_to_row = {r["_wp_title"]: r for r in chunk}
        pages_by_title = fetch_batch(session, host, list(title_to_row))

        for title, row in title_to_row.items():
            page = pages_by_title.get(title)
            info = extract_one(page) if page else {"page_status": "no_response"}
            out.append(
                {
                    "wikidata_id": row["wikidata_id"],
                    "name_en": row["name_en"],
                    "wp_lang": host.split(".", 1)[0],
                    "wp_url": row["_wp_url"],
                    "wp_title": title,
                    **info,
                }
            )
        pbar.update(len(chunk))
    return out


# ---------- main ---------------------------------------------------------


def main():
    if not INPUT_CSV.exists():
        sys.exit(f"missing input: {INPUT_CSV}")

    print(f"reading {INPUT_CSV}")
    by_host: dict[str, list[dict]] = defaultdict(list)
    n_in = 0
    with INPUT_CSV.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            n_in += 1
            url = row.get("any_wikipedia_url") or row.get("en_wikipedia_url")
            if not url:
                continue
            host = host_from_url(url)
            row["_wp_url"] = url
            row["_wp_title"] = title_from_url(url)
            by_host[host].append(row)

    total = sum(len(v) for v in by_host.values())
    print(
        f"  {n_in:,} input rows -> {total:,} with a Wikipedia URL "
        f"across {len(by_host)} wikis"
    )
    print(
        f"  top wikis: "
        + ", ".join(
            f"{h}({len(v):,})"
            for h, v in sorted(by_host.items(), key=lambda kv: -len(kv[1]))[:8]
        )
    )

    fieldnames = [
        "wikidata_id",
        "name_en",
        "wp_lang",
        "wp_url",
        "wp_title",
        "page_status",
        "page_length",
        "lead_extract_chars",
        "n_categories",
        "birth_year_from_cats",
        "death_year_from_cats",
        "lead_lifespan_birth",
        "lead_lifespan_death",
        "lead_born_year",
        "lead_died_year",
        "lead_floruit_start",
        "lead_floruit_end",
        "century_from_cats",
        "lead_extract",
    ]

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        with tqdm(total=total, desc="extracting", smoothing=0.05) as pbar:
            with ThreadPoolExecutor(max_workers=N_WORKERS) as pool:
                futs = {
                    pool.submit(process_host, h, rs, pbar): h
                    for h, rs in by_host.items()
                }
                for fut in as_completed(futs):
                    for row in fut.result():
                        writer.writerow(row)

    print(f"wrote {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
