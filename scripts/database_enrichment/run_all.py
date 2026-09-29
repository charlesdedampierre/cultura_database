import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from common import DATABASE, ROOT

HERE = Path(__file__).resolve().parent
TASK_LOG = ROOT / "task.log"

STEPS = (
    "01_is_settlement.py",
    "02_wikipedia_dates.py",
    "03_works_period.py",
    "04_is_scientist_is_artist.py",
    "05_is_human.py",
    "06_peak_productivity.py",
    "06b_western_continents_and_worlds.py",
    "07_notability.py",
    "08_polity_assignment.py",
)


def report(message):
    line = f"{datetime.now():%H:%M:%S}  enrichment       {message}"
    print(line, flush=True)
    with TASK_LOG.open("a") as handle:
        handle.write(line + "\n")


def main():
    report(f"{DATABASE}")
    for step in STEPS:
        started = time.time()
        report(f"{step} started")
        if subprocess.run([sys.executable, str(HERE / step)], cwd=HERE).returncode:
            report(f"{step} failed")
            raise SystemExit(1)
        report(f"{step} done in {(time.time() - started) / 60:.1f} min")


if __name__ == "__main__":
    main()
