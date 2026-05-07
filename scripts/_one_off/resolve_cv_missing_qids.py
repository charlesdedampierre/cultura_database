"""Resolve the 20,230 CV-only QIDs against Wikidata's current QID space.

Steps:
  1. Pull owl:sameAs from QLever, batched, to find canonical QIDs for any
     redirected entries.
  2. Categorize each CV QID:
       - alive_same       : QID still exists, no redirect
       - alive_redirected : QID redirected to a different canonical QID
       - missing          : QID returns no triple at all (probably deleted)
  3. Compare each canonical QID against Cultura's individuals:
       - already_in_cultura : the canonical QID is already known to Cultura
       - to_extract         : truly missing — needs Wikidata extraction

Outputs:
  data/cv_missing_from_cultura/qid_resolution.json
  data/cv_missing_from_cultura/qids_to_extract.json   (cohort for extractor)
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/wikidata_extraction_scripts_v2"))
from wikidata import qlever_rows, extract_qid  # noqa: E402

DB = ROOT / "data/humans_clean.sqlite3"
IN_QIDS = ROOT / "data/cv_missing_from_cultura/missing_qids.json"
OUT_RESOLUTION = ROOT / "data/cv_missing_from_cultura/qid_resolution.json"
OUT_TO_EXTRACT = ROOT / "data/cv_missing_from_cultura/qids_to_extract.json"

# QLever batch size for SPARQL VALUES — large, since each token is ~12 chars
BATCH = 5000


def existence_and_redirect(qids: list[str]) -> dict[str, dict]:
    """Return per-QID dict with keys: exists (bool), redirect (str|None).

    Two queries per batch:
      - owl:sameAs to detect redirects (and confirm existence)
      - schema:dateModified to detect existence for non-redirected QIDs
    """
    out: dict[str, dict] = {q: {"exists": False, "redirect": None} for q in qids}

    values = " ".join(f"wd:{q}" for q in qids)

    # 1. redirects
    redirect_q = f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
SELECT ?old ?new WHERE {{
  VALUES ?old {{ {values} }}
  ?old owl:sameAs ?new .
}}"""
    for row in qlever_rows(redirect_q):
        if len(row) < 2:
            continue
        old = extract_qid(row[0])
        new = extract_qid(row[1])
        if old in out:
            out[old] = {"exists": True, "redirect": new}

    # 2. for the ones not yet flagged as redirects, check existence via dateModified
    leftover = [q for q, info in out.items() if info["redirect"] is None]
    if leftover:
        leftover_values = " ".join(f"wd:{q}" for q in leftover)
        exist_q = f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX schema: <http://schema.org/>
SELECT ?h WHERE {{
  VALUES ?h {{ {leftover_values} }}
  ?h schema:dateModified ?d .
}}"""
        for row in qlever_rows(exist_q):
            qid = extract_qid(row[0])
            if qid in out:
                out[qid]["exists"] = True

    return out


def main() -> None:
    qids = json.loads(IN_QIDS.read_text())
    print(f"Loaded {len(qids):,} CV-only QIDs from {IN_QIDS.name}")

    resolution: dict[str, dict] = {}
    for i in tqdm(range(0, len(qids), BATCH), desc="QLever batches"):
        chunk = qids[i : i + BATCH]
        resolution.update(existence_and_redirect(chunk))

    n_alive_same = sum(1 for v in resolution.values() if v["exists"] and v["redirect"] is None)
    n_redirected = sum(1 for v in resolution.values() if v["redirect"] is not None)
    n_missing = sum(1 for v in resolution.values() if not v["exists"] and v["redirect"] is None)
    print("\nResolution summary:")
    print(f"  alive (no redirect)        : {n_alive_same:>6,}")
    print(f"  alive (redirected)         : {n_redirected:>6,}")
    print(f"  missing (deleted/no data)  : {n_missing:>6,}")

    # Compare canonical QIDs against Cultura
    print("\nChecking canonical QIDs against Cultura individuals...")
    canonical = {q: (info["redirect"] or q) for q, info in resolution.items() if info["exists"]}
    canonical_set = set(canonical.values())

    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("CREATE TEMP TABLE check_qids(qid TEXT PRIMARY KEY) WITHOUT ROWID;")
    cur.executemany("INSERT INTO check_qids VALUES (?);", [(q,) for q in canonical_set])
    cur.execute(
        "SELECT q.qid FROM check_qids q "
        "JOIN individuals i ON i.wikidata_id = q.qid;"
    )
    already_in = {r[0] for r in cur.fetchall()}
    con.close()

    n_already = len(already_in)
    n_to_extract = len(canonical_set) - n_already
    print(f"  canonical QIDs (unique)    : {len(canonical_set):>6,}")
    print(f"  ↳ already present in Cultura: {n_already:>6,}")
    print(f"  ↳ truly to-extract          : {n_to_extract:>6,}")

    # Persist
    OUT_RESOLUTION.write_text(json.dumps(resolution, ensure_ascii=False))
    print(f"\nWrote {OUT_RESOLUTION}")

    to_extract = sorted(canonical_set - already_in)
    OUT_TO_EXTRACT.write_text(json.dumps(to_extract, ensure_ascii=False))
    print(f"Wrote {OUT_TO_EXTRACT} ({len(to_extract):,} QIDs)")


if __name__ == "__main__":
    main()
