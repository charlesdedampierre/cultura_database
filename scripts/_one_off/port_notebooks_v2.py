"""Second pass: fix the schema gaps surfaced by the first bulk rerun.

Renames (whole-token, code cells only):
  - tables: sitelinks -> wikimedia_links, cities -> places,
            consolidate -> consolidated_database,
            cliopatria_polity_periods -> polities_periods_cliopatria
  - column: individuals_count -> number_individuals
  - precision swap: floruit_year and floruit_date  ->  floruit_period_start
      ONLY in cells that touch individuals_floruit_period or
      individuals_cliopatria. Cells that only use consolidated_database
      keep their floruit_year (that table has no period_start column).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK_DIRS = [ROOT / "notebooks", ROOT / "notebooks" / "use_cases"]

TABLE_RENAMES: list[tuple[str, str]] = [
    ("cliopatria_polity_periods", "polities_periods_cliopatria"),  # longest first
    ("sitelinks", "wikimedia_links"),
    ("cities", "places"),
    (r"\bconsolidate\b", "consolidated_database"),  # avoid "consolidated" already-renamed
]

COLUMN_RENAMES: list[tuple[str, str]] = [
    ("individuals_count", "number_individuals"),
]

PRECISION_TABLES = ("individuals_floruit_period", "individuals_cliopatria")


def apply_simple(src: str, pairs) -> tuple[str, int]:
    n = 0
    for old, new in pairs:
        if old.startswith("\\b"):
            pat = re.compile(old)
        else:
            pat = re.compile(rf"\b{re.escape(old)}\b")
        src, k = pat.subn(new, src)
        n += k
    return src, n


def apply_precision(src: str) -> tuple[str, int]:
    """Swap floruit_year / floruit_date -> floruit_period_start, but only when
    the cell references one of the tables that actually has that column."""
    if not any(t in src for t in PRECISION_TABLES):
        return src, 0
    n = 0
    for old in ("floruit_year", "floruit_date"):
        pat = re.compile(rf"\b{re.escape(old)}\b")
        src, k = pat.subn("floruit_period_start", src)
        n += k
    return src, n


def process_notebook(path: Path) -> tuple[int, int]:
    nb = json.loads(path.read_text())
    cells_changed = 0
    total = 0
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        original = "".join(cell["source"])
        ported, n1 = apply_simple(original, TABLE_RENAMES)
        ported, n2 = apply_simple(ported, COLUMN_RENAMES)
        ported, n3 = apply_precision(ported)
        n = n1 + n2 + n3
        if n:
            cell["source"] = ported.splitlines(keepends=True)
            cells_changed += 1
            total += n
    if total:
        path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n")
    return cells_changed, total


def main() -> int:
    changed_files = 0
    for d in NOTEBOOK_DIRS:
        for nb_path in sorted(d.glob("*.ipynb")):
            cells_changed, total = process_notebook(nb_path)
            status = "OK" if total else "skip"
            print(f"[{status}] {nb_path.relative_to(ROOT)} : {cells_changed} cells, {total} renames")
            if total:
                changed_files += 1
    print(f"\nTouched {changed_files} notebook file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
