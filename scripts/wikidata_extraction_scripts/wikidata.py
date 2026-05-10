"""Shared Wikidata client used by every extract_*.py script.

We use QLever (https://qlever.cs.uni-freiburg.de/api/wikidata) for bulk pulls
because it streams TSV results for queries that the official WDQS endpoint
times out on (e.g. "all Q5 humans with property X"). For small ad-hoc queries
(LIMIT 100, --test mode) we go direct to WDQS: it is more reliable for tiny
queries and decouples our smoke tests from QLever's uptime.

Public surface
--------------
    stream(query, endpoint="qlever")   -> yields list[str] rows (works for both)
    qlever_stream(query)               -> yields list[str] rows (TSV)
    wdqs_json(query)                   -> dict (full SPARQL JSON results)
    extract_qid(uri_or_token)          -> "Q42"
    clean_literal(token)               -> strips surrounding quotes / lang tag

All HTTP calls retry on 429/5xx with exponential backoff. ``extract_qid`` and
``clean_literal`` tolerate both QLever TSV (``<...>`` wrappers, ``"..."@en``
literals) and WDQS JSON (already clean).

Cohort filtering
----------------
When the env var ``WIKIDATA_TEST_COHORT_FILE`` points to a JSON file
containing a list (or dict keyed by) Q-IDs, every query that mentions
``?h wdt:P31 wd:Q5`` is rewritten to first restrict ``?h`` to that
cohort via a ``VALUES`` clause, and any trailing ``LIMIT`` is stripped
(the cohort itself caps the result). Endpoint is forced to QLever
because cohort sizes can exceed WDQS's URL/result limits. This lets the
test pipeline use a single shared sample of humans across all 14
extract scripts (so that downstream joins actually align).
"""
from __future__ import annotations

import json
import os
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Iterator

import requests


QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"
WDQS_ENDPOINT = "https://query.wikidata.org/sparql"

USER_AGENT = "cultura-database-research/1.0 (cdedampierre@bunka.ai)"
HEADERS = {"User-Agent": USER_AGENT}

DEFAULT_TIMEOUT = 600
MAX_RETRIES = 8


def _sleep_backoff(attempt: int, base: int = 5, cap: int = 300) -> None:
    time.sleep(min(base * (2 ** attempt), cap))


# --------------------------------------------------------------------------
# Cohort-restricted query rewrite
# --------------------------------------------------------------------------

_HUMAN_NEEDLE_RE = re.compile(r"\?h\s+wdt:P31\s+wd:Q5\s*\.")
_TRAILING_LIMIT_RE = re.compile(r"\s*LIMIT\s+\d+\s*$", re.IGNORECASE)


@lru_cache(maxsize=1)
def _load_cohort() -> tuple[str, ...]:
    """Read the cohort QIDs from $WIKIDATA_TEST_COHORT_FILE (JSON list or
    dict). Returns () when the env var is unset or the file is empty.
    Cached for the lifetime of the process — set the env var before the
    first call to ``stream()``.
    """
    path = os.environ.get("WIKIDATA_TEST_COHORT_FILE")
    if not path:
        return ()
    p = Path(path)
    if not p.exists():
        return ()
    with p.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        qids = data.get("qids") if "qids" in data else list(data.keys())
    else:
        qids = list(data)
    return tuple(q for q in qids if isinstance(q, str) and q.startswith("Q"))


def _values_clause(qids: tuple[str, ...]) -> str:
    return "VALUES ?h { " + " ".join(f"wd:{q}" for q in qids) + " }"


def _inject_cohort(query: str) -> str:
    """Rewrite a SPARQL query to restrict ``?h`` to the cohort. No-op when
    the cohort is empty or the query has no ``?h wdt:P31 wd:Q5 .`` clause.
    Also strips a trailing ``LIMIT N`` because the cohort itself caps results.
    """
    cohort = _load_cohort()
    if not cohort or not _HUMAN_NEEDLE_RE.search(query):
        return query
    values = _values_clause(cohort)
    rewritten = _HUMAN_NEEDLE_RE.sub(
        lambda m: values + "\n  " + m.group(0), query, count=1
    )
    return _TRAILING_LIMIT_RE.sub("", rewritten)


def qlever_stream(query: str, timeout: int = DEFAULT_TIMEOUT) -> Iterator[list[str]]:
    """Stream a QLever SPARQL query as TSV rows (header skipped).

    POSTs the query in the request body — GET would 414 on cohort-restricted
    queries that pack thousands of ``wd:Q...`` IDs into a ``VALUES`` clause.

    Each yielded value is a list of column strings — typically QID URIs and/or
    literals — exactly as QLever emits them. Use ``extract_qid`` and
    ``clean_literal`` to normalize.
    """
    headers = {**HEADERS, "Content-Type": "application/sparql-query",
               "Accept": "text/tab-separated-values"}

    response = None
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(
                QLEVER_ENDPOINT,
                data=query.encode("utf-8"),
                headers=headers,
                timeout=timeout,
                stream=True,
            )
        except requests.RequestException as exc:
            print(f"  network error: {exc}; retrying...")
            _sleep_backoff(attempt)
            continue

        if response.status_code in (429, 500, 502, 503, 504):
            print(f"  HTTP {response.status_code}; retrying...")
            _sleep_backoff(attempt)
            continue

        response.raise_for_status()
        break
    else:
        raise RuntimeError(f"QLever giving up after {MAX_RETRIES} retries")

    lines = response.iter_lines(decode_unicode=True)
    try:
        next(lines)  # header
    except StopIteration:
        return

    for line in lines:
        if not line:
            continue
        yield line.split("\t")


def qlever_rows(query: str, timeout: int = DEFAULT_TIMEOUT) -> list[list[str]]:
    """Materialize qlever_stream into a list. Use only for small queries."""
    return list(qlever_stream(query, timeout=timeout))


def wdqs_stream(query: str, timeout: int = 180) -> Iterator[list[str]]:
    """Stream rows from the official WDQS endpoint. Yields lists of column
    *values* (already unwrapped, in SELECT order)."""
    data = wdqs_json(query, timeout=timeout)
    head = data.get("head", {}).get("vars", [])
    for binding in data.get("results", {}).get("bindings", []):
        yield [binding.get(v, {}).get("value", "") for v in head]


def stream(query: str, *, endpoint: str = "qlever",
           timeout: int = DEFAULT_TIMEOUT) -> Iterator[list[str]]:
    """Stream rows from either QLever or WDQS.

    Use ``endpoint="wdqs"`` for tiny queries (LIMIT 100 / --test mode) — more
    reliable. Use ``endpoint="qlever"`` (default) for full-scale extracts.

    When a cohort file is configured (see module docstring), the query is
    rewritten to restrict ``?h`` to the cohort and the endpoint is forced
    to QLever.
    """
    query = _inject_cohort(query)
    if _load_cohort():
        endpoint = "qlever"
    if endpoint == "qlever":
        yield from qlever_stream(query, timeout=timeout)
    elif endpoint == "wdqs":
        yield from wdqs_stream(query, timeout=min(timeout, 180))
    else:
        raise ValueError(f"unknown endpoint: {endpoint!r} (use 'qlever' or 'wdqs')")


def wdqs_json(query: str, timeout: int = 180) -> dict:
    """Run a query against the official Wikidata SPARQL endpoint, JSON results."""
    headers = {**HEADERS, "Accept": "application/sparql-results+json"}
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(
                WDQS_ENDPOINT,
                params={"query": query},
                headers=headers,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            print(f"  network error: {exc}; retrying...")
            _sleep_backoff(attempt)
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            print(f"  HTTP {r.status_code}; retrying...")
            _sleep_backoff(attempt)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"WDQS giving up after {MAX_RETRIES} retries")


def extract_qid(token: str) -> str:
    """Turn '<http://www.wikidata.org/entity/Q42>' (or similar) into 'Q42'."""
    token = token.strip()
    if token.startswith("<") and token.endswith(">"):
        token = token[1:-1]
    if "/" in token:
        token = token.rsplit("/", 1)[-1]
    return token


def clean_literal(token: str) -> str:
    """Strip surrounding quotes and a trailing @lang tag from a TSV literal."""
    token = token.strip()
    if token.endswith('"@en') or "\"@" in token:
        token = token.split('"@', 1)[0] + '"'
    if token.startswith('"') and token.endswith('"'):
        token = token[1:-1]
    return token


def chunk(seq: Iterable, size: int) -> Iterator[list]:
    """Yield successive ``size``-sized chunks from ``seq``."""
    buf: list = []
    for item in seq:
        buf.append(item)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf
