"""Re-execute every notebook in-place against the latest humans_clean.sqlite3.

Top-level notebooks under notebooks/ run with cwd=notebooks/ (so `../data/...`
resolves to data/). Notebooks under notebooks/use_cases/ also run with
cwd=notebooks/ — those queries also write `../data/...` and `../cliopatria_data/...`.

Outputs:
    logs/notebook_runs/run_<timestamp>.log   per-notebook line + traceback on fail
    stderr: tqdm progress bar over notebooks
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK_ROOT = ROOT / "notebooks"
LOG_DIR = ROOT / "logs" / "notebook_runs"


def collect_notebooks(only: list[str] | None) -> list[Path]:
    nbs = sorted(NOTEBOOK_ROOT.glob("*.ipynb")) + sorted(
        (NOTEBOOK_ROOT / "use_cases").glob("*.ipynb")
    )
    if only:
        wanted = {n.lower() for n in only}
        nbs = [p for p in nbs if p.name.lower() in wanted or p.stem.lower() in wanted]
    return nbs


def execute_one(path: Path, timeout: int, log) -> tuple[bool, float, str | None]:
    started = time.time()
    nb = nbformat.read(path, as_version=4)
    # Always run with cwd=notebooks/ so `../data/...` and `../cliopatria_data/...`
    # resolve correctly regardless of whether the notebook lives at the top level
    # or under use_cases/.
    client = NotebookClient(
        nb,
        timeout=timeout,
        kernel_name="python3",
        resources={"metadata": {"path": str(NOTEBOOK_ROOT)}},
        allow_errors=False,
    )
    try:
        client.execute()
    except CellExecutionError as exc:
        elapsed = time.time() - started
        nbformat.write(nb, path)  # persist partial outputs incl. error
        log.write(f"\n--- TRACEBACK: {path.relative_to(ROOT)} ---\n")
        log.write(str(exc))
        log.write("\n")
        log.flush()
        return False, elapsed, str(exc).splitlines()[-1] if str(exc) else "CellExecutionError"
    except Exception as exc:  # noqa: BLE001
        elapsed = time.time() - started
        log.write(f"\n--- TRACEBACK: {path.relative_to(ROOT)} ---\n")
        log.write(traceback.format_exc())
        log.flush()
        return False, elapsed, f"{type(exc).__name__}: {exc}"
    elapsed = time.time() - started
    nbformat.write(nb, path)
    return True, elapsed, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=1800, help="per-cell seconds (default 1800)")
    ap.add_argument("--only", nargs="*", help="run only these notebook names (basename or stem)")
    ap.add_argument("--skip", nargs="*", default=[], help="skip these notebook names")
    args = ap.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"run_{ts}.log"

    nbs = collect_notebooks(args.only)
    skipset = {s.lower() for s in args.skip}
    nbs = [p for p in nbs if p.name.lower() not in skipset and p.stem.lower() not in skipset]

    if not nbs:
        print("No notebooks selected.", file=sys.stderr)
        return 1

    print(f"Logging to {log_path.relative_to(ROOT)}")
    print(f"Cell timeout: {args.timeout}s; {len(nbs)} notebook(s) queued.\n")

    results = []
    with log_path.open("w") as log:
        log.write(f"# notebook run {ts}\n")
        log.write(f"# timeout={args.timeout}s notebooks={len(nbs)}\n\n")
        bar = tqdm(nbs, desc="notebooks", unit="nb", file=sys.stderr)
        for path in bar:
            rel = path.relative_to(ROOT)
            bar.set_postfix_str(str(rel))
            ok, elapsed, err = execute_one(path, args.timeout, log)
            status = "OK  " if ok else "FAIL"
            line = f"[{status}] {elapsed:7.1f}s  {rel}"
            if err:
                line += f"   <- {err}"
            log.write(line + "\n")
            log.flush()
            print(line)
            results.append((ok, elapsed, rel, err))

    n_ok = sum(1 for r in results if r[0])
    n_fail = len(results) - n_ok
    total = sum(r[1] for r in results)
    print(f"\nDONE  {n_ok} ok, {n_fail} failed, total wall {total/60:.1f} min")
    print(f"Log: {log_path.relative_to(ROOT)}")
    return 0 if n_fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
