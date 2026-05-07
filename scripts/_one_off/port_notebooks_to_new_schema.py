"""Apply latest-DB schema renames to notebooks (code cells only).

Run from project root:
    .venv/bin/python scripts/_one_off/port_notebooks_to_new_schema.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK_DIRS = [ROOT / "notebooks", ROOT / "notebooks" / "use_cases"]

# Order matters: longer/more-specific replacements first.
RENAMES: list[tuple[str, str]] = [
    ("individuals_impact_date", "individuals_floruit_period"),
    ("nationalities_en", "country_of_citizenship_en"),
    ("sitelinks_count", "wikimedia_links_count"),
    # Column renames within the floruit_period table
    ("impact_date", "floruit_date"),
    ("impact_year", "floruit_year"),
]


def apply_renames(src: str) -> tuple[str, int]:
    n = 0
    for old, new in RENAMES:
        # Whole-token match: avoid partial substring collisions.
        pattern = re.compile(rf"\b{re.escape(old)}\b")
        src, k = pattern.subn(new, src)
        n += k
    return src, n


def fix_cliopatria_cells(src: str) -> tuple[str, int]:
    """individuals_cliopatria has no floruit_date column (only floruit_year).
    Rewrite `ic.floruit_date as floruit_year` -> `ic.floruit_year as floruit_year`.
    Catches the previously-renamed alias from `ic.impact_date as impact_year`.
    """
    pat = re.compile(r"(\b[a-zA-Z_]\w*)\.floruit_date(\s+as\s+floruit_year\b)", re.IGNORECASE)
    new_src, k = pat.subn(lambda m: f"{m.group(1)}.floruit_year{m.group(2)}", src)
    return new_src, k


def process_notebook(path: Path) -> tuple[int, int]:
    nb = json.loads(path.read_text())
    total_renames = 0
    cells_changed = 0
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        original = "".join(cell["source"])
        ported, n_basic = apply_renames(original)
        ported, n_clio = fix_cliopatria_cells(ported)
        n = n_basic + n_clio
        if n:
            cell["source"] = ported.splitlines(keepends=True)
            cells_changed += 1
            total_renames += n
    if total_renames:
        path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n")
    return cells_changed, total_renames


def main() -> int:
    changed_files = 0
    for d in NOTEBOOK_DIRS:
        for nb_path in sorted(d.glob("*.ipynb")):
            cells_changed, total = process_notebook(nb_path)
            status = "OK" if total else "skip"
            rel = nb_path.relative_to(ROOT)
            print(f"[{status}] {rel} : {cells_changed} cells, {total} renames")
            if total:
                changed_files += 1
    print(f"\nTouched {changed_files} notebook file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
