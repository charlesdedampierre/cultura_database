"""Run every enrichment step in order on CULTURA_DB, optionally on a fresh copy of a non-enriched base database."""

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from common import DATABASE, ROOT

DATABASE = DATABASE.resolve()

HERE = Path(__file__).resolve().parent
TASK_LOG = ROOT / "task.log"

STEPS = (
    "01_is_settlement.py",
    "02b_description_dates.py",
    "03_works_period.py",
    "04_is_scientist_is_artist.py",
    "05_is_human.py",
    "05b_cohort_age_stats.py",
    "06_peak_productivity.py",
    "06b_western_continents_and_worlds.py",
    "07_notability.py",
    "07b_polity_hierarchy.py",
    "08_polity_assignment.py",
)


def report(message):
    line = f"{datetime.now():%H:%M:%S}  enrichment       {message}"
    print(line, flush=True)
    with TASK_LOG.open("a") as handle:
        handle.write(line + "\n")


def copy_base(base):
    if DATABASE.exists():
        raise SystemExit(f"{DATABASE} already exists; enrichment from a base needs a new database")
    report(f"copying {base} to {DATABASE}")
    shutil.copyfile(base, DATABASE)
    DATABASE.chmod(0o644)


def main():
    parser = argparse.ArgumentParser(description="Run every enrichment step on CULTURA_DB.")
    parser.add_argument("--base", type=Path, help="non-enriched database copied to CULTURA_DB first, left untouched")
    base = parser.parse_args().base
    if base:
        copy_base(base)
    report(f"{DATABASE}")
    os.environ["CULTURA_DB"] = str(DATABASE)
    for step in STEPS:
        started = time.time()
        report(f"{step} started")
        if subprocess.run([sys.executable, str(HERE / step)], cwd=HERE).returncode:
            report(f"{step} failed")
            raise SystemExit(1)
        report(f"{step} done in {(time.time() - started) / 60:.1f} min")


if __name__ == "__main__":
    main()
