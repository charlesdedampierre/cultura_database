"""Fetch the first Wikidata revision for every individual that has no
external identifier and no Wikipedia/sitelink, so we can attribute each
item to a creation pathway (bot mass-import / QuickStatements / OpenRefine /
Mix'n'match / manual editor / etc.).

Resumable. Safe to Ctrl-C and re-run; already-fetched Q-ids are skipped.

Outputs:
  extraction_scripts/all_humans/.42.origin.jsonl   raw API records (append-only)
  data/humans_clean.sqlite3 :: individuals_origin  aggregated, classified table
"""
from __future__ import annotations

import json
import re
import signal
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

import requests
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "humans_clean.sqlite3"
OUT = Path(__file__).parent / ".42.origin.jsonl"
API = "https://www.wikidata.org/w/api.php"
HEADERS = {"User-Agent": "cultura-database-research/1.0 (cdedampierre@bunka.ai)"}
WORKERS = 12


def classify(user: str, comment: str, tags: list[str]) -> str:
    u = (user or "")
    ul = u.lower()
    c = (comment or "").lower()
    tg = " ".join(t.lower() for t in (tags or []))

    if "largedatasetbot" in ul:
        return "bot:LargeDatasetBot"
    if "gzwder" in ul:
        return "bot:GZWDer-flood"
    if "reinheitsgebot" in ul:
        return "bot:Reinheitsgebot"
    if "succubot" in ul:
        return "bot:SuccuBot"
    if "kasparbot" in ul:
        return "bot:KasparBot"
    if "edoderoobot" in ul:
        return "bot:Edoderoobot"
    if "botmultichill" in ul:
        return "bot:BotMultichill"
    if "arch2bot" in ul:
        return "bot:Arch2bot"
    if "matsubot" in ul:
        return "bot:MatSuBot"
    if "wikitrackbot" in ul:
        return "bot:WikiTrackBot"
    if "framabot" in ul:
        return "bot:Framabot"
    if "klbot" in ul:
        return "bot:KLBot2"
    if "sk!dbot" in ul or "skidbot" in ul:
        return "bot:Sk!dbot"
    if "magulbot" in ul:
        return "bot:MagulBot"
    if "emijrpbot" in ul:
        return "bot:Emijrpbot"
    if "cjmbot" in ul:
        return "bot:CJMbot"
    if "frettiebot" in ul:
        return "bot:Frettiebot"
    if "uallvbot" in ul:
        return "bot:UallvBot"
    if "cyclinginitbot" in ul:
        return "bot:CyclingInitBot"
    if "pi bot" in ul:
        return "bot:Pi-bot"
    if "quickstatementsbot" in ul:
        return "tool:QuickStatements"
    if ul.endswith("bot") or ul.endswith("bot)") or "(flood)" in ul or "bot " in ul:
        return f"bot:other"

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


def already_done(path: Path) -> set[str]:
    seen: set[str] = set()
    if not path.exists():
        return seen
    with path.open() as f:
        for line in f:
            try:
                seen.add(json.loads(line)["qid"])
            except Exception:
                pass
    return seen


def fetch_one(qid: str, session: requests.Session) -> dict | None:
    """Fetch the oldest revision of a single Q-id. Wikidata's revisions API
    only accepts rvdir=newer with one title at a time, so we cannot batch."""
    params = {
        "action": "query",
        "prop": "revisions",
        "titles": qid,
        "rvdir": "newer",
        "rvlimit": 1,
        "rvprop": "timestamp|user|comment|tags",
        "format": "json",
        "formatversion": 2,
        "maxlag": 5,
    }
    for attempt in range(5):
        try:
            r = session.get(API, params=params, headers=HEADERS, timeout=60)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            data = r.json()
            if "error" in data and data["error"].get("code") == "maxlag":
                time.sleep(5)
                continue
            break
        except requests.RequestException:
            if attempt == 4:
                return None
            time.sleep(2 ** attempt)
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


def aggregate_into_db():
    print("Aggregating .42.origin.jsonl into individuals_origin table...")
    conn = sqlite3.connect(DB)
    conn.execute("DROP TABLE IF EXISTS individuals_origin")
    conn.execute("""
        CREATE TABLE individuals_origin (
            wikidata_id TEXT PRIMARY KEY,
            first_revision_ts TEXT,
            first_user TEXT,
            first_comment TEXT,
            first_tags TEXT,
            pathway TEXT
        )
    """)
    rows = []
    with OUT.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            rows.append((
                r["qid"],
                r.get("timestamp"),
                r.get("user"),
                r.get("comment", ""),
                json.dumps(r.get("tags", [])),
                classify(r.get("user", ""), r.get("comment", ""), r.get("tags") or []),
            ))
            if len(rows) >= 50_000:
                conn.executemany(
                    "INSERT OR REPLACE INTO individuals_origin VALUES (?,?,?,?,?,?)",
                    rows,
                )
                rows.clear()
    if rows:
        conn.executemany(
            "INSERT OR REPLACE INTO individuals_origin VALUES (?,?,?,?,?,?)",
            rows,
        )
    conn.execute("CREATE INDEX idx_individuals_origin_pathway ON individuals_origin(pathway)")
    conn.commit()

    print("\nPathway breakdown:")
    for pathway, n in conn.execute(
        "SELECT pathway, COUNT(*) FROM individuals_origin GROUP BY pathway ORDER BY COUNT(*) DESC"
    ):
        print(f"  {n:>10,}  {pathway}")
    conn.close()


def main():
    if "--aggregate-only" in sys.argv:
        aggregate_into_db()
        return

    conn = sqlite3.connect(DB)
    targets = [
        r[0]
        for r in conn.execute(
            "SELECT wikidata_id FROM individuals "
            "WHERE identifiers_count = 0 AND sitelinks_count = 0"
        )
    ]
    conn.close()

    done = already_done(OUT)
    todo = [q for q in targets if q not in done]
    rate_per_worker = 5  # req/s
    total_rate = WORKERS * rate_per_worker
    print(f"Total target Q-ids: {len(targets):,}")
    print(f"Already fetched:    {len(done):,}")
    print(f"Remaining to fetch: {len(todo):,}")
    print(f"Workers:            {WORKERS}")
    print(f"Estimated time:     ~{len(todo) / total_rate / 3600:.1f}h "
          f"(at ~{total_rate} req/s)")

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=WORKERS, pool_maxsize=WORKERS)
    session.mount("https://", adapter)

    interrupted = {"flag": False}

    def on_sigint(signum, frame):
        interrupted["flag"] = True
        print("\n[graceful stop requested]")

    signal.signal(signal.SIGINT, on_sigint)

    write_lock = Lock()
    out_f = OUT.open("a")
    pbar = tqdm(total=len(todo), desc="fetch", smoothing=0.02)

    def worker(qid: str):
        rec = fetch_one(qid, session)
        if rec is not None:
            line = json.dumps(rec)
            with write_lock:
                out_f.write(line + "\n")
        return qid

    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futures = {ex.submit(worker, q): q for q in todo[:WORKERS * 4]}
            cursor = WORKERS * 4
            while futures:
                if interrupted["flag"]:
                    for f in futures:
                        f.cancel()
                    break
                done_set, _ = next(iter([(set(), set())]))  # placeholder for type
                done_set = set()
                for f in as_completed(list(futures.keys()), timeout=None):
                    futures.pop(f, None)
                    pbar.update(1)
                    if cursor < len(todo) and not interrupted["flag"]:
                        nxt = todo[cursor]
                        cursor += 1
                        futures[ex.submit(worker, nxt)] = nxt
                    if interrupted["flag"]:
                        break
    finally:
        pbar.close()
        out_f.close()

    print("\nDone fetching. Run with --aggregate-only to build the SQLite table:")
    print("  python extraction_scripts/all_humans/42_fetch_all_no_provenance_origin.py --aggregate-only")


if __name__ == "__main__":
    main()
