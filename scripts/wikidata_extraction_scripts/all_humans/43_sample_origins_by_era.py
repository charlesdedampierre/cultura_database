"""For 500 individuals before 1800 and 500 after 1800 (no Wikipedia link,
no external identifier), fetch the oldest Wikidata revision and write
sample_origins_<era>.csv with: qid, timestamp, user, pathway, comment, url."""
import csv
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from tqdm import tqdm

API = "https://www.wikidata.org/w/api.php"
HEADERS = {"User-Agent": "cultura-database-research/1.0 (cdedampierre@bunka.ai)"}
WORKERS = 12

ERAS = {
    "after_1800": Path("/tmp/qids_after_1800_500.txt"),
    "before_1800": Path("/tmp/qids_before_1800.txt"),
}
OUT_DIR = Path(__file__).parent


def classify(user: str, comment: str, tags) -> str:
    u = user or ""
    ul = u.lower()
    c = (comment or "").lower()
    tg = " ".join((tags or []))
    if "largedatasetbot" in ul: return "bot:LargeDatasetBot"
    if "gzwder" in ul: return "bot:GZWDer-flood"
    if "reinheitsgebot" in ul: return "bot:Reinheitsgebot"
    if "succubot" in ul: return "bot:SuccuBot"
    if "kasparbot" in ul: return "bot:KasparBot"
    if "edoderoobot" in ul: return "bot:Edoderoobot"
    if "botmultichill" in ul: return "bot:BotMultichill"
    if "arch2bot" in ul: return "bot:Arch2bot"
    if "matsubot" in ul: return "bot:MatSuBot"
    if "wikitrackbot" in ul: return "bot:WikiTrackBot"
    if "framabot" in ul: return "bot:Framabot"
    if "klbot" in ul: return "bot:KLBot2"
    if "skidbot" in ul or "sk!dbot" in ul: return "bot:Sk!dbot"
    if "magulbot" in ul: return "bot:MagulBot"
    if "emijrpbot" in ul: return "bot:Emijrpbot"
    if "cjmbot" in ul: return "bot:CJMbot"
    if "frettiebot" in ul: return "bot:Frettiebot"
    if "uallvbot" in ul: return "bot:UallvBot"
    if "cyclinginitbot" in ul: return "bot:CyclingInitBot"
    if "pi bot" in ul: return "bot:Pi-bot"
    if "legobot" in ul: return "bot:Legobot"
    if "quickstatementsbot" in ul: return "tool:QuickStatements"
    if ul.endswith("bot") or "(flood)" in ul: return "bot:other"
    if "openrefine" in c or "openrefine" in tg or "editgroups/b/or/" in c:
        return "tool:OpenRefine"
    if "quickstatements" in c or "quickstatements" in tg:
        return "tool:QuickStatements"
    if "mix-n-match" in c or "mix'n'match" in c or "mix_n_match" in c:
        return "tool:Mix'n'match"
    if "data import hub" in c or "imported from " in c:
        return "manual:data-import-hub"
    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", u):
        return "manual:anonymous-IP"
    return "manual:human-editor"


def fetch_one(qid, session):
    params = {
        "action": "query", "prop": "revisions", "titles": qid,
        "rvdir": "newer", "rvlimit": 1,
        "rvprop": "timestamp|user|comment|tags",
        "format": "json", "formatversion": 2, "maxlag": 5,
    }
    data = None
    for attempt in range(4):
        try:
            r = session.get(API, params=params, headers=HEADERS, timeout=30)
            if r.status_code == 429:
                time.sleep(2 ** attempt); continue
            r.raise_for_status()
            data = r.json()
            if "error" in data and data["error"].get("code") == "maxlag":
                time.sleep(3); continue
            break
        except requests.RequestException:
            if attempt == 3: return None
            time.sleep(2 ** attempt)
    if data is None: return None
    pages = data.get("query", {}).get("pages", [])
    if not pages or "revisions" not in pages[0]: return None
    rev = pages[0]["revisions"][0]
    return {
        "qid": qid,
        "timestamp": rev.get("timestamp"),
        "user": rev.get("user"),
        "comment": rev.get("comment", "") or "",
        "tags": rev.get("tags", []),
    }


def run_era(era: str, qids_file: Path):
    qids = [q.strip() for q in qids_file.read_text().splitlines() if q.strip()]
    session = requests.Session()
    session.mount("https://", requests.adapters.HTTPAdapter(
        pool_connections=WORKERS, pool_maxsize=WORKERS))

    records = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch_one, q, session): q for q in qids}
        for f in tqdm(as_completed(futs), total=len(futs), desc=f"{era}"):
            rec = f.result()
            if rec is not None:
                rec["pathway"] = classify(rec["user"], rec["comment"], rec["tags"])
                records.append(rec)

    out_csv = OUT_DIR / f"sample_origins_{era}.csv"
    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["qid", "timestamp", "user", "pathway", "comment", "url"])
        for r in sorted(records, key=lambda x: x["timestamp"] or ""):
            w.writerow([
                r["qid"], r["timestamp"], r["user"], r["pathway"],
                r["comment"][:200],
                f"https://www.wikidata.org/wiki/{r['qid']}",
            ])

    from collections import Counter
    cat = Counter(r["pathway"] for r in records)
    print(f"\n{era}  (n={len(records)})  →  {out_csv}")
    for k, v in cat.most_common():
        print(f"  {v:4d}  ({v/len(records)*100:5.1f}%)  {k}")
    return records


if __name__ == "__main__":
    for era, path in ERAS.items():
        run_era(era, path)
