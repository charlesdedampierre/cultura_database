import itertools
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "datamodels"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import raw_file_readers

DATABASE = Path(os.environ.get("CULTURA_DB", ROOT / "data" / "cultura_v2.duckdb"))
TASK_LOG = ROOT / "task.log"
CHUNK = int(os.environ.get("CHUNK", "1000000"))
FLOOR_GB = float(os.environ.get("FLOOR_GB", "3"))
LIMIT = int(os.environ["LIMIT"]) if os.environ.get("LIMIT") else None


def open_database():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(DATABASE))


def free_gb():
    return shutil.disk_usage(DATABASE.parent).free / 1e9


def check_disk():
    free = free_gb()
    if free < FLOOR_GB:
        raise SystemExit(f"stopping: {free:.1f} GB free on {DATABASE.parent}, below the {FLOOR_GB} GB floor")


def report(step, message):
    line = f"{datetime.now():%H:%M:%S}  {step:16} {message}"
    print(line, flush=True)
    with TASK_LOG.open("a") as handle:
        handle.write(line + "\n")


def chunks(iterable, size=CHUNK):
    iterator = iter(iterable)
    while batch := list(itertools.islice(iterator, size)):
        yield batch


def limited(items):
    return items[:LIMIT] if LIMIT else items


def keys_of(path, reader=None):
    read = reader or raw_file_readers.pairs_until_truncated
    return sorted(key for key, _ in read(path))


def done(step, tables):
    filled = "  ".join(f"{table.name}={table.count:,}" for table in tables)
    report(step, f"done   {filled}   db {DATABASE.stat().st_size / 1e9:.1f} GB   free {free_gb():.0f} GB")
