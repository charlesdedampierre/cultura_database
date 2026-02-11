"""Shared SPARQL wrapper for querying Wikidata."""

import sys
import time

import pandas as pd
from SPARQLWrapper import JSON, SPARQLWrapper


ENDPOINT_URL = "https://query.wikidata.org/sparql"
USER_AGENT = "CulturaDatabase Python/%s.%s" % (sys.version_info[0], sys.version_info[1])

MAX_RETRIES = 3
RETRY_DELAY = 30  # seconds


def sparql_query(query: str) -> list[dict]:
    """Execute a SPARQL query against Wikidata and return list of dicts.

    Each dict has keys matching the SPARQL SELECT variables,
    with values already extracted from the JSON response.
    Retries on transient errors (timeout, 429, 500).
    """
    sparql = SPARQLWrapper(ENDPOINT_URL, agent=USER_AGENT)
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)

    for attempt in range(MAX_RETRIES):
        try:
            response = sparql.query().convert()
            bindings = response["results"]["bindings"]
            rows = []
            for b in bindings:
                row = {}
                for key, val in b.items():
                    row[key] = val.get("value", "")
                rows.append(row)
            return rows
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_DELAY * (attempt + 1)
                print(f"  SPARQL error (attempt {attempt + 1}): {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


def sparql_query_df(query: str) -> pd.DataFrame:
    """Execute a SPARQL query and return results as a DataFrame."""
    rows = sparql_query(query)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)
