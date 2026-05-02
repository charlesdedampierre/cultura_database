"""Build a reusable cohort of Q5 humans for the test pipeline.

The full extraction is hours; the integration test only needs a small,
deterministic sample of humans where every per-property extract script
sees the **same** set so downstream joins (in
``_build_clean_test.py`` and the consolidation scripts) actually align.

Two subcommands:

    extract   one-time pull of N Q-IDs from QLever, cached on disk.
    sample    deterministic random pick of M QIDs out of the cached pool.

Outputs (default locations under ``data/test_cohort/``):

    cohort_100k.json     full cached pool (one-time, ~a few MB)
    cohort_sample.json   the rolling 1k sub-sample used by tests

Usage
-----
    # one-time (~1 minute against QLever)
    python scripts/wikidata_extraction_scripts_v2/00_extract_cohort.py extract

    # cheap, repeatable
    python scripts/wikidata_extraction_scripts_v2/00_extract_cohort.py sample --n 1000

The downstream extract scripts read the sample via the
``WIKIDATA_TEST_COHORT_FILE`` env var (handled in ``wikidata.py``).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wikidata import extract_qid, qlever_stream  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = ROOT / "data" / "test_cohort"
DEFAULT_COHORT_FILE = DEFAULT_DIR / "cohort_100k.json"
DEFAULT_SAMPLE_FILE = DEFAULT_DIR / "cohort_sample.json"

POOL_QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?h WHERE {{
  ?h wdt:P31 wd:Q5 .
}}
LIMIT {n}
"""


def cmd_extract(args) -> int:
    out = Path(args.out)
    if out.exists() and not args.force:
        existing = json.loads(out.read_text())
        print(f"[cohort] {out} already exists with {len(existing):,} QIDs "
              f"(use --force to refetch)")
        return 0

    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"[cohort] pulling {args.n:,} Q5 QIDs from QLever -> {out}")
    qids: list[str] = []
    for row in tqdm(qlever_stream(POOL_QUERY.format(n=args.n)),
                    total=args.n, desc="cohort", unit=" qid"):
        if not row:
            continue
        qid = extract_qid(row[0])
        if qid.startswith("Q"):
            qids.append(qid)

    out.write_text(json.dumps(qids))
    print(f"[cohort] saved {len(qids):,} QIDs")
    return 0


def cmd_sample(args) -> int:
    src = Path(args.src)
    if not src.exists():
        print(f"[cohort] source pool {src} missing — run "
              f"`00_extract_cohort.py extract` first")
        return 1
    pool = json.loads(src.read_text())
    if len(pool) < args.n:
        print(f"[cohort] pool has {len(pool):,} QIDs but you asked for "
              f"{args.n:,} — sampling all")
        chosen = pool
    else:
        rng = random.Random(args.seed)
        chosen = rng.sample(pool, args.n)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(chosen))
    print(f"[cohort] sampled {len(chosen):,} QIDs (seed={args.seed}) -> {out}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ext = sub.add_parser("extract", help="One-time pull from QLever.")
    p_ext.add_argument("--n", type=int, default=100_000)
    p_ext.add_argument("--out", default=str(DEFAULT_COHORT_FILE))
    p_ext.add_argument("--force", action="store_true",
                       help="Refetch even if the cohort file already exists.")
    p_ext.set_defaults(func=cmd_extract)

    p_smp = sub.add_parser("sample", help="Pick a sub-sample for tests.")
    p_smp.add_argument("--n", type=int, default=1_000)
    p_smp.add_argument("--src", default=str(DEFAULT_COHORT_FILE))
    p_smp.add_argument("--out", default=str(DEFAULT_SAMPLE_FILE))
    p_smp.add_argument("--seed", type=int, default=42)
    p_smp.set_defaults(func=cmd_sample)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
