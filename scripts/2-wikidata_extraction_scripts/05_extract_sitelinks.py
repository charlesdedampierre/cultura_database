"""Extract every sitelink (Wikipedia / Wikiquote / Wikisource / ...) for
every Q5 human.

Output:
    data/all_humans/sitelinks.json   {human_qid: [url, url, ...]}
    data/all_humans/sitelinks.test.json (in --test mode)

Run:
    python wikidata_extraction_scripts_v2/05_extract_sitelinks.py --test
    python wikidata_extraction_scripts_v2/05_extract_sitelinks.py
"""
from __future__ import annotations

import os
import pathlib

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wikidata import extract_qid, stream  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = pathlib.Path(os.environ["WIKIDATA_OUT_DIR"]) if os.environ.get("WIKIDATA_OUT_DIR") else ROOT / "data" / "all_humans" / "wikidata_extraction_scripts_v2"

QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX schema: <http://schema.org/>

SELECT ?h ?sitelink WHERE {{
  ?h wdt:P31 wd:Q5 .
  ?sitelink schema:about ?h .
}}{limit}
"""


def fetch(limit: int | None, endpoint: str) -> dict[str, list[str]]:
    suffix = f"\nLIMIT {limit}" if limit else ""
    out: dict[str, list[str]] = defaultdict(list)
    for row in tqdm(stream(QUERY.format(limit=suffix), endpoint=endpoint),
                    desc="  sitelinks", unit=" rows"):
        if len(row) < 2:
            continue
        qid = extract_qid(row[0])
        if not qid.startswith("Q"):
            continue
        url = row[1].strip().strip("<>")
        if url:
            out[qid].append(url)
    return dict(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test", action="store_true",
                        help="Run a tiny LIMIT 100 sample.")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    limit = (int(os.environ.get("WIKIDATA_TEST_LIMIT", "100")) if args.test else None)
    endpoint = "wdqs" if args.test else "qlever"
    out_file = OUT_DIR / ("sitelinks.test.json" if args.test else "sitelinks.json")

    print(f"[05] extracting sitelinks ({'TEST' if args.test else 'FULL'} mode, endpoint={endpoint})")
    sitelinks = fetch(limit, endpoint)
    total_urls = sum(len(v) for v in sitelinks.values())
    print(f"\n[05] {len(sitelinks):,} humans with sitelinks "
          f"({total_urls:,} URLs total)")

    with out_file.open("w") as f:
        json.dump(sitelinks, f, ensure_ascii=False)
    print(f"[05] saved {out_file}")

    print("\n[05] sample:")
    for qid, urls in list(sitelinks.items())[:5]:
        print(f"  {qid}: {len(urls)} URLs, e.g. {urls[0] if urls else '-'}")


if __name__ == "__main__":
    main()
