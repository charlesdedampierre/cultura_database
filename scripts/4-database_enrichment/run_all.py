"""Copy the non-enriched database to CULTURA_DB and run every enrichment step on the copy, in order, so the non-enriched one is never touched."""

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from common import BASE, DATABASE, ROOT

DATABASE = DATABASE.resolve()

HERE = Path(__file__).resolve().parent
TASK_LOG = ROOT / "task.log"

STEPS = (
    "01_place_is_settlement.py",
    "02_individual_dates_from_description.py",
    "03_individual_works_period.py",
    "04_individual_is_scientist_artist_human.py",
    "05_cohort_life_expectancy_and_floruit_age.py",
    "06_individual_peak_activity_window.py",
    "07_western_continents_and_cultural_worlds.py",
    "08_individual_notability.py",
    "09_polity_hierarchy.py",
    "10_individual_polity_assignment.py",
)


def report(message):
    line = f"{datetime.now():%H:%M:%S}  enrichment       {message}"
    print(line, flush=True)
    with TASK_LOG.open("a") as handle:
        handle.write(line + "\n")


def copy_base(base):
    if DATABASE.exists():
        raise SystemExit(f"{DATABASE} already exists; move it away or set CULTURA_DB to a new database")
    report(f"copying {base} to {DATABASE}")
    shutil.copyfile(base, DATABASE)
    DATABASE.chmod(0o644)


def main():
    parser = argparse.ArgumentParser(description="Run every enrichment step on CULTURA_DB.")
    parser.add_argument("--base", type=Path, default=BASE, help="non-enriched database copied to CULTURA_DB first, left untouched")
    copy_base(parser.parse_args().base)
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
