"""Copy the non-enriched database to CULTURA_DB (cultura_enriched_v3.2) and run the enrichment steps on the copy, in order, so the non-enriched one is never touched.

The former date and polity steps (now in legacy/) are left out: 01_notebooks_dates replaces them."""

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb

from common import BASE, DATABASE, ROOT, D
from pydantic_to_duckdb_schema import columns_of

DATABASE = DATABASE.resolve()

HERE = Path(__file__).resolve().parent
TASK_LOG = ROOT / "task.log"

STEPS = (
    "08_occupation_meta_occupation.py",
    "13_individual_dates_from_life_expectancy.py",
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
    reset_individual_enriched()


def reset_individual_enriched():
    """The non-enriched database holds an empty individual_enriched with the former columns: recreate it with the current datamodel."""
    connection = duckdb.connect(str(DATABASE))
    assert connection.execute("SELECT count(*) FROM individual_enriched").fetchone()[0] == 0
    declared = ", ".join(f'"{column}" {kind}' for column, kind in columns_of(D.IndividualEnriched).items())
    connection.execute(f"CREATE OR REPLACE TABLE individual_enriched ({declared})")
    connection.close()


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
