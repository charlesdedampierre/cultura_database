"""
Step 3: Enrich polities with Wikipedia URLs and Wikidata IDs.

Handles:
- Converting Wikipedia article titles to full URLs
- Resolving Wikipedia redirects
- Fetching Wikidata IDs from Wikipedia titles

Input/Output: data/cliopatria.db
"""

import sqlite3
import requests
import time
import urllib.parse
from pathlib import Path
from tqdm import tqdm

SCRIPT_DIR = Path(__file__).parent
DB_PATH = SCRIPT_DIR / "data" / "cliopatria.db"

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
HEADERS = {
    "User-Agent": "CliopatriaProcessor/1.0 (https://github.com/cultura-database)"
}
BATCH_SIZE = 50


def title_to_url(title: str) -> str:
    """Convert Wikipedia article title to full URL."""
    if not title:
        return None
    url_title = title.replace(" ", "_")
    url_title = urllib.parse.quote(url_title, safe="_")
    return f"https://en.wikipedia.org/wiki/{url_title}"


def resolve_redirect(title: str) -> str:
    """Resolve Wikipedia redirect to get canonical title."""
    params = {
        "action": "query",
        "titles": title,
        "redirects": 1,
        "format": "json"
    }

    try:
        resp = requests.get(WIKIPEDIA_API, params=params, headers=HEADERS, timeout=30)
        data = resp.json()

        redirects = data.get("query", {}).get("redirects", [])
        if redirects:
            return redirects[-1].get("to", title)

        normalized = data.get("query", {}).get("normalized", [])
        if normalized:
            return normalized[-1].get("to", title)

        return title

    except Exception as e:
        return title


def get_wikidata_ids_batch(titles: list[str]) -> dict[str, str]:
    """Get Wikidata IDs for a batch of Wikipedia titles."""
    if not titles:
        return {}

    params = {
        "action": "wbgetentities",
        "sites": "enwiki",
        "titles": "|".join(titles),
        "props": "info|sitelinks",
        "format": "json"
    }

    try:
        resp = requests.get(WIKIDATA_API, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        results = {}
        for qid, entity in data.get("entities", {}).items():
            if qid.startswith("Q"):
                enwiki = entity.get("sitelinks", {}).get("enwiki", {})
                title = enwiki.get("title")
                if title:
                    results[title] = qid

        return results

    except Exception as e:
        print(f"Error fetching batch: {e}")
        return {}


def enrich_wikipedia_urls(conn):
    """Add Wikipedia URLs to all polities."""
    cursor = conn.cursor()

    cursor.execute("SELECT id, wikipedia FROM polities WHERE wikipedia IS NOT NULL")
    polities = cursor.fetchall()

    print(f"Adding Wikipedia URLs for {len(polities)} polities...")

    for polity_id, title in tqdm(polities, desc="Adding Wikipedia URLs"):
        url = title_to_url(title)
        cursor.execute(
            "UPDATE polities SET wikipedia_url = ? WHERE id = ?",
            (url, polity_id)
        )

    conn.commit()
    return len(polities)


def enrich_wikidata_ids(conn):
    """Fetch and add Wikidata IDs for all polities."""
    cursor = conn.cursor()

    # Get unique Wikipedia titles
    cursor.execute("""
        SELECT DISTINCT wikipedia FROM polities
        WHERE wikipedia IS NOT NULL AND wikipedia != ''
    """)
    all_titles = [row[0] for row in cursor.fetchall()]

    print(f"Fetching Wikidata IDs for {len(all_titles)} unique titles...")

    # Split into batches
    batches = [all_titles[i:i + BATCH_SIZE] for i in range(0, len(all_titles), BATCH_SIZE)]

    # Fetch Wikidata IDs
    title_to_qid = {}
    for batch in tqdm(batches, desc="Fetching Wikidata IDs"):
        results = get_wikidata_ids_batch(batch)
        title_to_qid.update(results)
        time.sleep(0.1)

    # Update database
    updated = 0
    for title, qid in title_to_qid.items():
        cursor.execute(
            "UPDATE polities SET wikidata_id = ? WHERE wikipedia = ?",
            (qid, title)
        )
        updated += cursor.rowcount

    conn.commit()
    return updated, len(all_titles) - len(title_to_qid)


def fix_remaining_with_redirects(conn):
    """Fix remaining polities by resolving Wikipedia redirects."""
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT wikipedia FROM polities
        WHERE wikidata_id IS NULL AND wikipedia IS NOT NULL
    """)
    remaining_titles = [row[0] for row in cursor.fetchall()]

    if not remaining_titles:
        return 0

    print(f"Resolving redirects for {len(remaining_titles)} remaining titles...")

    fixed = 0
    for title in tqdm(remaining_titles, desc="Resolving redirects"):
        # Resolve redirect
        canonical = resolve_redirect(title)

        # Get Wikidata ID for canonical title
        results = get_wikidata_ids_batch([canonical])

        if results:
            qid = list(results.values())[0]
            cursor.execute(
                "UPDATE polities SET wikidata_id = ? WHERE wikipedia = ?",
                (qid, title)
            )
            fixed += cursor.rowcount

        time.sleep(0.1)

    conn.commit()
    return fixed


def print_summary(conn):
    """Print enrichment summary."""
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM polities")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM polities WHERE wikipedia_url IS NOT NULL")
    with_url = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM polities WHERE wikidata_id IS NOT NULL")
    with_wikidata = cursor.fetchone()[0]

    print(f"\n{'='*60}")
    print("WIKIPEDIA ENRICHMENT COMPLETE")
    print(f"{'='*60}")
    print(f"Total polities: {total}")
    print(f"With Wikipedia URL: {with_url} ({100*with_url/total:.1f}%)")
    print(f"With Wikidata ID: {with_wikidata} ({100*with_wikidata/total:.1f}%)")

    # Show missing
    cursor.execute("""
        SELECT name, wikipedia FROM polities
        WHERE wikidata_id IS NULL
        LIMIT 10
    """)
    missing = cursor.fetchall()
    if missing:
        print(f"\nStill missing Wikidata ID ({total - with_wikidata}):")
        for name, wiki in missing:
            print(f"  - {name} ({wiki})")


if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH, timeout=30)

    enrich_wikipedia_urls(conn)
    enrich_wikidata_ids(conn)
    fix_remaining_with_redirects(conn)
    print_summary(conn)

    conn.close()
