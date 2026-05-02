"""End-to-end smoke test of the v2 pipeline on a 1 K cohort sample.

Wires together three pipeline stages so a single command exercises the
whole chain:

    1. Wikidata extraction   (scripts/wikidata_extraction_scripts_v2/)
    2. SQLite integration    (scripts/database_integration_scripts_V2/)
    3. Consolidation         (this directory: 01 floruit + 02..04 Cliopatria)

The trick that makes step 1 cohort-aware: a single JSON file with the
chosen QIDs is referenced by ``WIKIDATA_TEST_COHORT_FILE``. Every
extraction query gets a ``VALUES ?h { wd:Q... }`` clause injected by
``wikidata.py``, so all 14 extracts see the *same* cohort and the
downstream joins actually align.

Stages 2 + 3 read whichever DB is named in ``CULTURA_DB_PATH`` (defaults
to ``data/humans_clean_test.sqlite3``), so the test never touches the
real ``humans_clean.sqlite3``.

Usage
-----
    # First time: pull the 100 K pool (~1 minute on QLever).
    python scripts/wikidata_extraction_scripts_v2/00_extract_cohort.py extract

    # Repeatable end-to-end test:
    python scripts/database_consolidation/test_full_pipeline.py
        --cohort-size 1000     # default
        --skip-extract         # reuse last *.test.json (faster)
        --skip-cliopatria      # if the V3 GeoJSON isn't around
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXTRACT_DIR = ROOT / "scripts" / "wikidata_extraction_scripts_v2"
INTEG_DIR = ROOT / "scripts" / "database_integration_scripts_V2"
CONSOL_DIR = ROOT / "scripts" / "database_consolidation"
DATA_DIR = ROOT / "data"

COHORT_DIR = DATA_DIR / "test_cohort"
COHORT_POOL = COHORT_DIR / "cohort_100k.json"
COHORT_SAMPLE = COHORT_DIR / "cohort_sample.json"
TEST_DB = DATA_DIR / "humans_clean_test.sqlite3"
CLIOPATRIA_GEOJSON = (
    ROOT / "cliopatria_data" / "cliopatria_V2"
    / "cliopatria_polities_only_v3.geojson"
)


def _load(module_path: Path):
    spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_path.stem] = mod
    spec.loader.exec_module(mod)
    return mod


def banner(msg: str) -> None:
    bar = "=" * 70
    print(f"\n{bar}\n  {msg}\n{bar}", flush=True)


def step(msg: str) -> None:
    print(f"\n>>> {msg}", flush=True)


def ensure_pool(args) -> None:
    """If the 100 K pool is missing, fetch it (one-time)."""
    if COHORT_POOL.exists():
        size = len(json.loads(COHORT_POOL.read_text()))
        print(f"[pool] reusing {COHORT_POOL} ({size:,} QIDs)")
        return
    step(f"pulling {args.pool_size:,} Q5 QIDs from QLever (one-time)")
    cmd = [
        sys.executable,
        str(EXTRACT_DIR / "00_extract_cohort.py"),
        "extract", "--n", str(args.pool_size), "--out", str(COHORT_POOL),
    ]
    subprocess.run(cmd, check=True)


def sample_cohort(args) -> None:
    step(f"sampling {args.cohort_size:,} QIDs out of the pool (seed={args.seed})")
    cmd = [
        sys.executable,
        str(EXTRACT_DIR / "00_extract_cohort.py"),
        "sample",
        "--n", str(args.cohort_size),
        "--src", str(COHORT_POOL),
        "--out", str(COHORT_SAMPLE),
        "--seed", str(args.seed),
    ]
    subprocess.run(cmd, check=True)


def run_extraction(env: dict[str, str]) -> None:
    step("running wikidata_extraction_scripts_v2/run_all.py --test")
    cmd = [sys.executable, str(EXTRACT_DIR / "run_all.py"), "--test"]
    t0 = time.time()
    subprocess.run(cmd, check=True, env=env)
    print(f"[extract] {time.time() - t0:.1f}s")


def run_integration(env: dict[str, str]) -> None:
    step("running database_integration_scripts_V2/_build_clean_test.py")
    cmd = [sys.executable, str(INTEG_DIR / "_build_clean_test.py")]
    t0 = time.time()
    subprocess.run(cmd, check=True, env=env)
    print(f"[integ] {time.time() - t0:.1f}s")


def run_floruit(env: dict[str, str]) -> None:
    step("running database_consolidation/01_individuals_floruit_period.py --full")
    cmd = [
        sys.executable,
        str(CONSOL_DIR / "01_individuals_floruit_period.py"),
        "--full",
    ]
    t0 = time.time()
    subprocess.run(cmd, check=True, env=env)
    print(f"[floruit] {time.time() - t0:.1f}s")


def run_cliopatria(env: dict[str, str]) -> None:
    if not CLIOPATRIA_GEOJSON.exists():
        print(f"[cliopatria] SKIPPING — {CLIOPATRIA_GEOJSON} not found")
        return
    for script in ("02_create_polities_cliopatria.py",
                   "03_copy_polity_periods.py",
                   "04_individuals_cliopatria.py"):
        step(f"running database_consolidation/{script} --full")
        cmd = [sys.executable, str(CONSOL_DIR / script), "--full"]
        t0 = time.time()
        subprocess.run(cmd, check=True, env=env)
        print(f"[{script}] {time.time() - t0:.1f}s")


# Tables we expect to exist after each stage, with a minimum row count.
EXPECTED_AFTER_INTEG = {
    "individuals": 1,
    "places": 1,
    "country_of_citizenship": 1,
    "occupations": 1,
    "writing_languages": 1,
    "identifier_types": 1,
    "wikimedia_links": 1,
}
EXPECTED_AFTER_FLORUIT = {
    "individuals_floruit_period": 1,
}
EXPECTED_AFTER_CLIOPATRIA = {
    "polities_cliopatria": 1,
    "polities_periods_cliopatria": 1,
    # individuals_cliopatria can be 0 for a small cohort if no QID lands
    # inside any polity polygon — keep a soft floor.
    "individuals_cliopatria": 0,
}


def verify(stage: str, expectations: dict[str, int]) -> list[str]:
    failures: list[str] = []
    with sqlite3.connect(TEST_DB) as conn:
        for table, min_rows in expectations.items():
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not row:
                failures.append(f"  [{stage}] missing table: {table}")
                continue
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            ok = n >= min_rows
            print(f"  [{stage}] {table:34s} rows={n:>6}  (min {min_rows})  "
                  f"{'ok' if ok else 'FAIL'}")
            if not ok:
                failures.append(f"  [{stage}] {table}: {n} < {min_rows}")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cohort-size", type=int, default=1_000)
    parser.add_argument("--pool-size", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--skip-extract", action="store_true",
                        help="Skip the wikidata extraction step (reuse the "
                             "*.test.json that's already on disk).")
    parser.add_argument("--skip-cliopatria", action="store_true")
    args = parser.parse_args()

    banner("v2 pipeline end-to-end test (cohort-restricted)")

    COHORT_DIR.mkdir(parents=True, exist_ok=True)
    ensure_pool(args)
    sample_cohort(args)

    env = os.environ.copy()
    env["WIKIDATA_TEST_COHORT_FILE"] = str(COHORT_SAMPLE)
    env["CULTURA_DB_PATH"] = str(TEST_DB)

    if args.skip_extract:
        print("[extract] SKIPPED (per --skip-extract)")
    else:
        run_extraction(env)

    run_integration(env)
    fail_integ = verify("integration", EXPECTED_AFTER_INTEG)

    run_floruit(env)
    fail_floruit = verify("floruit", EXPECTED_AFTER_FLORUIT)

    fail_clio: list[str] = []
    if not args.skip_cliopatria:
        run_cliopatria(env)
        fail_clio = verify("cliopatria", EXPECTED_AFTER_CLIOPATRIA)
    else:
        print("[cliopatria] SKIPPED (per --skip-cliopatria)")

    failures = fail_integ + fail_floruit + fail_clio
    banner("RESULT")
    if failures:
        print("FAILED:")
        for f in failures:
            print(f)
        sys.exit(1)
    print(f"OK — test DB at {TEST_DB}")


if __name__ == "__main__":
    main()
