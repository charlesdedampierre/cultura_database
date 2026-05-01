"""Find 500 individuals before 1800 and 500 after 1800 that are truly
orphaned on Wikidata: zero external-ID claims AND zero sitelinks
(verified live, not via the local DB which only knows ~2,300 of the
~30,000 external-ID property types).

For each kept Q-id, fetch the oldest revision and classify the creation
pathway.

Output: extraction_scripts/all_humans/sample_orphans_<era>.csv
"""
import csv
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "humans_clean.sqlite3"
OUT_DIR = Path(__file__).parent
API = "https://www.wikidata.org/w/api.php"
ENT_API = "https://www.wikidata.org/wiki/Special:EntityData"
HEADERS = {"User-Agent": "cultura-database-research/1.0 (cdedampierre@bunka.ai)"}
WORKERS = 10
TARGET_PER_ERA = 500

ERAS = {
    "after_1800": "c.impact_year >= 1800",
    "before_1800": "c.impact_year < 1800",
}


def classify(user, comment, tags):
    u = user or ""; ul = u.lower()
    c = (comment or "").lower(); tg = " ".join(tags or [])
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


def verify_orphan(qid: str, session: requests.Session) -> dict | None:
    """Return entity info if the item has zero external-IDs and zero sitelinks
    on the live Wikidata entity, else None."""
    url = f"{ENT_API}/{qid}.json"
    for attempt in range(3):
        try:
            r = session.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            data = r.json()
            break
        except Exception:
            if attempt == 2:
                return None
            time.sleep(2 ** attempt)
    ents = data.get("entities") or {}
    if qid not in ents:
        return None
    ent = ents[qid]
    sitelinks = ent.get("sitelinks") or {}
    if len(sitelinks) > 0:
        return None
    claims = ent.get("claims") or {}
    ext_id_props = []
    for pid, stmts in claims.items():
        for s in stmts:
            dt = (s.get("mainsnak") or {}).get("datatype")
            if dt == "external-id":
                ext_id_props.append(pid)
                break
    if ext_id_props:
        return None
    return {"qid": qid, "n_claims": len(claims)}


def fetch_first_rev(qid, session):
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


def candidate_qids(era_filter: str, n: int) -> list[str]:
    conn = sqlite3.connect(DB)
    rows = conn.execute(f"""
        SELECT i.wikidata_id
        FROM individuals i
        JOIN consolidate c ON i.wikidata_id = c.wikidata_id
        WHERE i.identifiers_count = 0
          AND i.sitelinks_count = 0
          AND {era_filter}
        ORDER BY RANDOM()
        LIMIT {n}
    """).fetchall()
    conn.close()
    return [r[0] for r in rows]


def run_era(era: str, era_filter: str):
    print(f"\n========== {era} ==========")
    pool_size = TARGET_PER_ERA * 25  # ~93% rejection rate — heavy oversample
    candidates = candidate_qids(era_filter, pool_size)
    print(f"Drew {len(candidates)} candidates from local DB; verifying live...")

    session = requests.Session()
    session.mount("https://", requests.adapters.HTTPAdapter(
        pool_connections=WORKERS, pool_maxsize=WORKERS))

    kept = []
    rejected = 0
    pbar = tqdm(total=TARGET_PER_ERA, desc=f"verify {era}")
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(verify_orphan, q, session): q for q in candidates}
        for f in as_completed(futs):
            res = f.result()
            if res is None:
                rejected += 1
                continue
            kept.append(res["qid"])
            pbar.update(1)
            if len(kept) >= TARGET_PER_ERA:
                for fut in futs:
                    fut.cancel()
                break
    pbar.close()
    print(f"  kept: {len(kept)}   rejected (had ext-IDs or sitelinks on live WD): {rejected}")

    print(f"Fetching first revisions for {len(kept)} verified orphans...")
    records = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch_first_rev, q, session): q for q in kept}
        for f in tqdm(as_completed(futs), total=len(futs), desc=f"origins {era}"):
            rec = f.result()
            if rec:
                rec["pathway"] = classify(rec["user"], rec["comment"], rec["tags"])
                records.append(rec)

    out = OUT_DIR / f"sample_orphans_{era}.csv"
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["qid", "timestamp", "user", "pathway", "comment", "url"])
        for r in sorted(records, key=lambda x: x["timestamp"] or ""):
            w.writerow([
                r["qid"], r["timestamp"], r["user"], r["pathway"],
                r["comment"][:200], f"https://www.wikidata.org/wiki/{r['qid']}",
            ])

    cat = Counter(r["pathway"] for r in records)
    print(f"\n{era}: n={len(records)}  →  {out}")
    for k, v in cat.most_common():
        print(f"  {v:4d}  ({v/len(records)*100:5.1f}%)  {k}")


if __name__ == "__main__":
    for era, era_filter in ERAS.items():
        run_era(era, era_filter)
