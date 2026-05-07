"""Fast cohort catalogs extractor — replaces the per-property loop in
06_extract_catalogs.py for small cohorts.

Single QLever query per batch of QIDs returns every external-ID triple
(human, property, value), filtered to ExternalId properties. Writes
catalogs.json in the same format as the original script.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/wikidata_extraction_scripts_v2"))
from wikidata import qlever_rows, extract_qid, clean_literal  # noqa: E402

CV_DIR = ROOT / "data/cv_missing_from_cultura"
COHORT = CV_DIR / "qids_to_extract.json"
OUT_DIR = CV_DIR / "wikidata_extract"
OUT_FILE = OUT_DIR / "catalogs.json"

BATCH = 100  # small batches to dodge QLever 429s


def main() -> None:
    qids = json.loads(COHORT.read_text())
    print(f"cohort size: {len(qids)}")

    out: dict[str, dict[str, list[str]]] = {}
    n_triples = 0
    for i in tqdm(range(0, len(qids), BATCH), desc="catalogs"):
        chunk = qids[i : i + BATCH]
        values = " ".join(f"wd:{q}" for q in chunk)
        q = f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wikibase: <http://wikiba.se/ontology#>
SELECT ?h ?prop ?v WHERE {{
  VALUES ?h {{ {values} }}
  ?h ?p ?v .
  ?prop wikibase:directClaim ?p .
  ?prop wikibase:propertyType wikibase:ExternalId .
}}"""
        for retry in range(5):
            try:
                rows = qlever_rows(q)
                break
            except Exception as exc:
                wait = 2 ** retry * 5
                print(f"  retry in {wait}s after {exc}")
                time.sleep(wait)
        else:
            raise RuntimeError(f"giving up on batch starting at {i}")

        for row in rows:
            if len(row) < 3:
                continue
            h = extract_qid(row[0])
            pid = extract_qid(row[1])
            v = clean_literal(row[2])
            out.setdefault(h, {}).setdefault(pid, []).append(v)
            n_triples += 1

    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False))
    print(f"\nwrote {OUT_FILE}")
    print(f"  humans with at least one identifier: {len(out):,}")
    print(f"  total identifier values             : {n_triples:,}")


if __name__ == "__main__":
    main()
