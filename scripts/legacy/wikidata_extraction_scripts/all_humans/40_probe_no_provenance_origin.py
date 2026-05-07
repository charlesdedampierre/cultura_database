"""Sample no-catalog/no-sitelink individuals and pull their first Wikidata
revision (creator + comment + tags) to identify how they were added."""
import json
import sys
import time
from collections import Counter
from pathlib import Path

import requests
from tqdm import tqdm

QIDS_FILE = Path("/tmp/no_provenance_qids.txt")
OUT_FILE = Path(__file__).parent / ".40.out.jsonl"
API = "https://www.wikidata.org/w/api.php"
HEADERS = {"User-Agent": "cultura-database-research/1.0 (cdedampierre@bunka.ai)"}


def first_revision(qid: str, session: requests.Session) -> dict | None:
    params = {
        "action": "query",
        "prop": "revisions",
        "titles": qid,
        "rvdir": "newer",
        "rvlimit": 1,
        "rvprop": "timestamp|user|comment|tags|ids",
        "format": "json",
        "formatversion": 2,
    }
    r = session.get(API, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    pages = data.get("query", {}).get("pages", [])
    if not pages or "revisions" not in pages[0]:
        return None
    rev = pages[0]["revisions"][0]
    return {
        "qid": qid,
        "timestamp": rev.get("timestamp"),
        "user": rev.get("user"),
        "comment": rev.get("comment", ""),
        "tags": rev.get("tags", []),
    }


def classify(rec: dict) -> str:
    user = (rec.get("user") or "").lower()
    comment = (rec.get("comment") or "").lower()
    tags = [t.lower() for t in rec.get("tags") or []]
    if "bot" in user:
        if "viaf" in user or "viaf" in comment:
            return "bot:VIAF"
        if "reinheitsgebot" in user:
            return "bot:Reinheitsgebot (sitelink import)"
        if "kasparbot" in user:
            return "bot:KasparBot"
        if "edoderoobot" in user:
            return "bot:Edoderoobot"
        if "matsuhirobot" in user or "ladsgroupbot" in user:
            return f"bot:{user}"
        return f"bot:{user}"
    if "openrefine" in comment or "openrefine" in " ".join(tags):
        return "tool:OpenRefine"
    if "quickstatements" in comment or "quickstatements" in " ".join(tags):
        return "tool:QuickStatements"
    if "mix'n'match" in comment or "mix-n-match" in comment or "mix_n_match" in comment:
        return "tool:Mix'n'match"
    if "wikidata-mobile" in " ".join(tags) or "mobile edit" in " ".join(tags):
        return "manual:mobile"
    if "from " in comment and "wikipedia" in comment:
        return "manual:from-wikipedia-article"
    if "created a new item" in comment and not comment.replace("created a new item", "").strip(": "):
        return "manual:bare-create"
    return f"manual:{user}"


def main():
    qids = [q.strip() for q in QIDS_FILE.read_text().splitlines() if q.strip()]
    session = requests.Session()
    records = []
    with OUT_FILE.open("w") as out:
        for qid in tqdm(qids, desc="fetch first rev"):
            try:
                rec = first_revision(qid, session)
                if rec is None:
                    continue
                rec["category"] = classify(rec)
                records.append(rec)
                out.write(json.dumps(rec) + "\n")
            except Exception as e:
                print(f"\n[warn] {qid}: {e}", file=sys.stderr)
            time.sleep(0.05)

    cat = Counter(r["category"] for r in records)
    users = Counter(r["user"] for r in records)
    print("\n=== category breakdown ===")
    for k, v in cat.most_common():
        print(f"  {v:4d}  {k}")
    print("\n=== top creators ===")
    for k, v in users.most_common(15):
        print(f"  {v:4d}  {k}")
    print(f"\nTotal sampled: {len(records)} (out of {len(qids)} requested)")


if __name__ == "__main__":
    main()
