"""Rewrite notebooks in `notebooks/` (excluding `use_cases/`) so they read
from `humans_clean.duckdb` instead of `humans_clean.sqlite3`.

Conversions performed per code cell:
  - `import sqlite3`                                 → `import duckdb`
  - `"../data/humans_clean.sqlite3"`                 → `"../data/humans_clean.duckdb"`
  - `sqlite3.connect(X)`                             → `duckdb.connect(X, read_only=True)`
  - `pl.read_database(SQL, conn)`                    → `conn.execute(SQL).pl()`
  - `pl.read_database(SQL, conn, execute_options={'parameters': P})`
                                                     → `conn.execute(SQL, P).pl()`
  - `pd.read_sql_query(SQL, conn)` / `pd.read_sql(SQL, conn)`
                                                     → `conn.execute(SQL).df()`
  - removes `conn.execute('PRAGMA cache_size=...')` lines (DuckDB doesn't expose
    that PRAGMA — it manages memory itself).

Markdown cells: `humans_clean.sqlite3` → `humans_clean.duckdb`.

The script is idempotent: running it twice on a converted notebook is a no-op.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NB_DIR = REPO / "notebooks"


def _split_balanced_args(text: str) -> list[str]:
    """Split a parenthesised arg list on top-level commas, respecting nesting
    and string literals. Input is the body inside the outer parens."""
    args: list[str] = []
    depth = 0
    in_str: str | None = None
    last = 0
    i = 0
    while i < len(text):
        c = text[i]
        if in_str is not None:
            if c == "\\" and i + 1 < len(text):
                i += 2
                continue
            if c == in_str:
                in_str = None
        else:
            if c in ("'", '"'):
                in_str = c
                # detect triple-quote
                if text[i:i + 3] == c * 3:
                    end = text.find(c * 3, i + 3)
                    if end == -1:
                        i = len(text)
                        continue
                    i = end + 3
                    in_str = None
                    continue
            elif c in "([{":
                depth += 1
            elif c in ")]}":
                depth -= 1
            elif c == "," and depth == 0:
                args.append(text[last:i])
                last = i + 1
        i += 1
    args.append(text[last:])
    return [a.strip() for a in args]


def _find_call(src: str, fn: str) -> tuple[int, int, str] | None:
    """Find the first call to `fn(...)` (handling balanced parens / strings).
    Returns (start, end_exclusive, args_text) or None."""
    pat = re.compile(r"\b" + re.escape(fn) + r"\(")
    m = pat.search(src)
    if not m:
        return None
    start = m.start()
    i = m.end() - 1  # position of '('
    depth = 0
    in_str: str | None = None
    j = i
    while j < len(src):
        c = src[j]
        if in_str is not None:
            if c == "\\" and j + 1 < len(src):
                j += 2
                continue
            if c == in_str:
                in_str = None
        else:
            if c in ("'", '"'):
                if src[j:j + 3] == c * 3:
                    end = src.find(c * 3, j + 3)
                    if end == -1:
                        return None
                    j = end + 3
                    continue
                in_str = c
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return start, j + 1, src[i + 1:j]
        j += 1
    return None


def _convert_pl_read_database(src: str) -> str:
    while True:
        hit = _find_call(src, "pl.read_database")
        if hit is None:
            break
        start, end, args_text = hit
        args = _split_balanced_args(args_text)
        if len(args) < 2:
            break
        sql_arg = args[0]
        conn_arg = args[1].strip()
        params_text = None
        for a in args[2:]:
            m = re.match(r"execute_options\s*=\s*\{(.*)\}\s*$", a, flags=re.S)
            if m:
                inner = m.group(1)
                pm = re.search(
                    r"['\"]parameters['\"]\s*:\s*(.+?)\s*,?\s*$",
                    inner, flags=re.S,
                )
                if pm:
                    params_text = pm.group(1).strip().rstrip(",").strip()
        if params_text is None:
            replacement = f"{conn_arg}.execute({sql_arg}).pl()"
        else:
            replacement = (
                f"{conn_arg}.execute({sql_arg}, {params_text}).pl()"
            )
        src = src[:start] + replacement + src[end:]
    return src


def _convert_pd_read_sql(src: str) -> str:
    for fn in ("pd.read_sql_query", "pd.read_sql"):
        while True:
            hit = _find_call(src, fn)
            if hit is None:
                break
            start, end, args_text = hit
            args = _split_balanced_args(args_text)
            if len(args) < 2:
                break
            sql_arg = args[0]
            conn_arg = args[1].strip()
            params_text = None
            for a in args[2:]:
                m = re.match(r"params\s*=\s*(.+)", a, flags=re.S)
                if m:
                    params_text = m.group(1).strip().rstrip(",").strip()
            if params_text is None:
                replacement = f"{conn_arg}.execute({sql_arg}).df()"
            else:
                replacement = (
                    f"{conn_arg}.execute({sql_arg}, {params_text}).df()"
                )
            src = src[:start] + replacement + src[end:]
    return src


def convert_code_source(src: str) -> str:
    src = re.sub(r"^(\s*)import\s+sqlite3\s*$", r"\1import duckdb",
                 src, flags=re.M)
    src = re.sub(
        r"^(\s*)import\s+sqlite3\s*,\s*([^\n]+)$",
        r"\1import duckdb\n\1import \2",
        src,
        flags=re.M,
    )
    src = src.replace("humans_clean.sqlite3", "humans_clean.duckdb")
    src = re.sub(
        r"\bsqlite3\.connect\(\s*([^)]+?)\s*\)",
        r"duckdb.connect(\1, read_only=True)",
        src,
    )
    src = re.sub(
        r"^\s*(?:conn|con)\.execute\(\s*['\"]PRAGMA\s+cache_size\s*=\s*-?\d+['\"]\s*\)\s*\n",
        "",
        src,
        flags=re.M,
    )
    src = _convert_pl_read_database(src)
    src = _convert_pd_read_sql(src)
    return src


def convert_markdown_source(src: str) -> str:
    return src.replace("humans_clean.sqlite3", "humans_clean.duckdb")


def convert_cell(cell: dict) -> bool:
    src = cell.get("source", "")
    text = "".join(src) if isinstance(src, list) else src
    if cell.get("cell_type") == "code":
        new = convert_code_source(text)
    elif cell.get("cell_type") == "markdown":
        new = convert_markdown_source(text)
    else:
        return False
    if new == text:
        return False
    cell["source"] = new.splitlines(keepends=True)
    if cell.get("cell_type") == "code":
        cell["outputs"] = []
        cell["execution_count"] = None
    return True


def convert_notebook(path: Path) -> tuple[int, int]:
    nb = json.loads(path.read_text())
    changed_cells = 0
    for cell in nb.get("cells", []):
        if convert_cell(cell):
            changed_cells += 1
    if changed_cells:
        path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n")
    return changed_cells, len(nb.get("cells", []))


def main():
    paths = sorted(p for p in NB_DIR.glob("*.ipynb"))
    print(f"converting {len(paths)} notebooks in {NB_DIR}")
    total_changed = 0
    for p in paths:
        n_changed, n_total = convert_notebook(p)
        if n_changed:
            total_changed += 1
            print(f"  ✓ {p.name:60s} {n_changed:>2}/{n_total} cells")
        else:
            print(f"    {p.name:60s} no change")
    print(f"\n{total_changed}/{len(paths)} notebooks rewritten")


if __name__ == "__main__":
    main()
