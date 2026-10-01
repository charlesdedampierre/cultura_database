"""Path A — step 4.

Aggregate per-property JSONs (one file per property under
`data/all_humans/identifiers_per_property/`) into a single TSV that the
Rust SQLite-loader can stream-insert.

Output: data/all_humans/all_human_identifiers_v2.tsv
Columns (tab-separated): wikidata_id, property_id, value
Header row included.

A summary JSON (per-property row counts) is written to
`data/all_humans/all_human_identifiers_v2_summary.json`.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

def _find_root(start: Path) -> Path:
    p = start
    for _ in range(8):
        if (p / "data" / "humans_clean.sqlite3").exists():
            return p
        p = p.parent
    return Path(__file__).resolve().parents[3]


ROOT = _find_root(Path(__file__).resolve())
IN_DIR = ROOT / "data" / "all_humans" / "identifiers_per_property"
OUT_TSV = ROOT / "data" / "all_humans" / "all_human_identifiers_v2.tsv"
OUT_SUMMARY = ROOT / "data" / "all_humans" / "all_human_identifiers_v2_summary.json"
TASK_LOG = ROOT / "task.log"


def log(msg: str) -> None:
    stamped = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(stamped, flush=True)
    with TASK_LOG.open("a") as f:
        f.write(stamped + "\n")


def main() -> None:
    if not IN_DIR.exists():
        log(f"[48] no per-property JSONs at {IN_DIR}; run script 47 first")
        sys.exit(1)

    files = sorted(IN_DIR.glob("P*.json"), key=lambda p: int(p.stem[1:]))
    log(f"[48] aggregating {len(files):,} per-property JSONs")

    summary: dict[str, int] = {}
    total_rows = 0
    n_errors = 0

    OUT_TSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_TSV.open("w", encoding="utf-8") as out:
        out.write("wikidata_id\tproperty_id\tvalue\n")
        for i, fp in enumerate(files, 1):
            try:
                d = json.loads(fp.read_text())
            except Exception as e:
                log(f"[48]   skipping {fp.name}: parse error {e}")
                n_errors += 1
                continue
            pid = d.get("pid") or fp.stem
            if d.get("error"):
                summary[pid] = -1
                n_errors += 1
                continue
            pairs = d.get("pairs", [])
            summary[pid] = len(pairs)
            for qid, value in pairs:
                value = (value or "").replace("\t", " ").replace("\n", " ")
                out.write(f"{qid}\t{pid}\t{value}\n")
                total_rows += 1
            if i % 500 == 0:
                log(f"[48]   {i}/{len(files)} files, total rows so far: {total_rows:,}")

    OUT_SUMMARY.write_text(json.dumps({
        "aggregated_at": datetime.now().isoformat(timespec="seconds"),
        "n_files": len(files),
        "n_errors": n_errors,
        "total_rows": total_rows,
        "rows_per_property": summary,
    }, indent=2))

    log(f"[48] DONE: {total_rows:,} rows from {len(files)-n_errors} props "
        f"(errors: {n_errors}) -> {OUT_TSV}")


if __name__ == "__main__":
    main()
