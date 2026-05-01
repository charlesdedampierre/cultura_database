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
"""
from __future__ import annotations

import time
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


def qlever_stream(query: str, timeout: int = DEFAULT_TIMEOUT) -> Iterator[list[str]]:
    """Stream a QLever SPARQL query as TSV rows (header skipped).

    Each yielded value is a list of column strings — typically QID URIs and/or
    literals — exactly as QLever emits them. Use ``extract_qid`` and
    ``clean_literal`` to normalize.
    """
    params = {"query": query, "action": "tsv_export"}

    response = None
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(
                QLEVER_ENDPOINT,
                params=params,
                headers=HEADERS,
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
    """
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
