"""Quick plot: active individuals per decade in 'Greek City-States' polity.

Excludes century-precision rows (floruit span >= 50 years) — keeps only
people whose floruit window is decade- or quarter-century-precise.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

DB = Path("/Users/charlesdedampierre/Desktop/Rsearch Folder/cultura_database/data/humans_clean.sqlite3")
POLITY_ID = 39  # Greek City-States
SPAN_MAX = 50   # exclude century-precision (span ~ 99) and worse


def main() -> None:
    with sqlite3.connect(DB) as conn:
        df = pd.read_sql_query(
            """
            SELECT floruit_period_start AS start, floruit_period_end AS end
            FROM individuals_cliopatria
            WHERE ';' || polity_id || ';' LIKE '%;' || ? || ';%'
              AND floruit_period_start IS NOT NULL
              AND floruit_period_end   IS NOT NULL
              AND (floruit_period_end - floruit_period_start) < ?
            """,
            conn,
            params=(POLITY_ID, SPAN_MAX),
        )

    print(f"Kept {len(df)} individuals (span < {SPAN_MAX} yrs)")

    # Decade bin: floor to nearest 10
    def decade(y: int) -> int:
        return int(y // 10 * 10)

    rows = []
    for s, e in zip(df["start"], df["end"]):
        d_start = decade(s)
        d_end = decade(e)
        for d in range(d_start, d_end + 1, 10):
            rows.append(d)

    counts = pd.Series(rows).value_counts().sort_index()

    # Reindex to a continuous decade axis
    full = range(counts.index.min(), counts.index.max() + 10, 10)
    counts = counts.reindex(full, fill_value=0)

    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.bar(counts.index, counts.values, width=8, color="#2b3a55", edgecolor="none")
    ax.set_xlabel("Decade")
    ax.set_ylabel("Active individuals")
    ax.set_title(f"Greek City-States — active individuals per decade  (n={len(df)})")
    ax.grid(axis="y", alpha=0.25, linewidth=0.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    out = Path(__file__).with_suffix(".png")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
