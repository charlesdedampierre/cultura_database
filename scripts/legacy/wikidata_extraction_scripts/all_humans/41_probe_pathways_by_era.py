"""Compare creation pathways for no-catalog/no-sitelink individuals
before vs. after 1800. For each pathway, keep one example Q-id."""
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests
from tqdm import tqdm

API = "https://www.wikidata.org/w/api.php"
HEADERS = {"User-Agent": "cultura-database-research/1.0 (cdedampierre@bunka.ai)"}

ERAS = {
    "after_1800": Path("/tmp/qids_after_1800.txt"),
    "before_1800": Path("/tmp/qids_before_1800.txt"),
}
OUT_DIR = Path(__file__).parent


def first_revision(qid: str, session: requests.Session) -> dict | None:
    params = {
        "action": "query",
        "prop": "revisions",
        "titles": qid,
        "rvdir": "newer",
        "rvlimit": 1,
        "rvprop": "timestamp|user|comment|tags",
        "format": "json",
        "formatversion": 2,
    }
    r = session.get(API, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    pages = r.json().get("query", {}).get("pages", [])
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
    user = (rec.get("user") or "")
    ul = user.lower()
    c = (rec.get("comment") or "").lower()
    tags = " ".join(rec.get("tags") or []).lower()
    if "largedatasetbot" in ul:
        return "bot:LargeDatasetBot (mass import)"
    if "gzwder" in ul:
        return "bot:GZWDer flood (mass import)"
    if "quickstatementsbot" in ul or "quickstatements" in c or "quickstatements" in tags:
        return "tool:QuickStatements"
    if "openrefine" in c or "openrefine" in tags or "editgroups/b/or/" in c:
        return "tool:OpenRefine"
    if "mix'n'match" in c or "mix-n-match" in c or "mix_n_match" in c:
        return "tool:Mix'n'match"
    if "reinheitsgebot" in ul:
        return "bot:Reinheitsgebot (SourceMD/Wikipedia mirror)"
    if "succubot" in ul:
        return "bot:SuccuBot"
    if "edoderoobot" in ul:
        return "bot:Edoderoobot"
    if "botmultichill" in ul:
        return "bot:BotMultichill (RKD/art catalogs)"
    if "kasparbot" in ul:
        return "bot:KasparBot"
    if "bot" in ul:
        return f"bot:other ({user})"
    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", user):
        return "manual:anonymous-IP"
    return "manual:human-editor"


def main():
    session = requests.Session()
    by_era = {}

    for era, path in ERAS.items():
        qids = [q.strip() for q in path.read_text().splitlines() if q.strip()]
        records = []
        out_file = OUT_DIR / f".41.{era}.out.jsonl"
        with out_file.open("w") as out:
            for qid in tqdm(qids, desc=f"fetch {era}"):
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
        by_era[era] = records

    for era, records in by_era.items():
        cat = Counter(r["category"] for r in records)
        examples = defaultdict(list)
        for r in records:
            examples[r["category"]].append(r)

        print(f"\n========== {era}  (n={len(records)}) ==========")
        for k, v in cat.most_common():
            ex = examples[k][0]
            url = f"https://www.wikidata.org/wiki/{ex['qid']}"
            comment = (ex.get("comment") or "").replace("\n", " ")[:80]
            print(f"  {v:4d}  ({v/len(records)*100:5.1f}%)  {k}")
            print(f"           example: {ex['qid']:<14} ({ex['timestamp'][:10]}) "
                  f"user={ex['user']:<22}  {url}")
            print(f"           comment: {comment}")


if __name__ == "__main__":
    main()
