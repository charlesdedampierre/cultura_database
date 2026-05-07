"""Quick diagnostic: who is missing a floruit period? who is missing a polity?

Two questions:
  1) Among individuals without a floruit period — is there a pattern in
     occupation or country of citizenship?
  2) Among individuals without a polity assignment (not in
     individuals_cliopatria) — is there a pattern in occupation or in
     birth/floruit year?

Outputs counts to stdout and writes a 2x2 figure to <this>.png.
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from tqdm import tqdm

DB = Path("/Users/charlesdedampierre/Desktop/Rsearch Folder/cultura_database/data/humans_clean.sqlite3")
TOP_N = 15
CHUNK = 200_000


def split_field(s: str | None) -> list[str]:
    if not s:
        return []
    parts = [p.strip() for p in s.split(";")]
    return [p for p in parts if p]


def stream_counter(conn: sqlite3.Connection, sql: str, col: str, total: int) -> Counter:
    """Counter over a multi-valued (semicolon) text column streamed in chunks."""
    c: Counter = Counter()
    cur = conn.execute(sql)
    pbar = tqdm(total=total, desc=col, unit="row")
    while True:
        rows = cur.fetchmany(CHUNK)
        if not rows:
            break
        for (val,) in rows:
            for v in split_field(val):
                c[v] += 1
        pbar.update(len(rows))
    pbar.close()
    return c


def main() -> None:
    with sqlite3.connect(DB) as conn:
        # Some occupations rows have invalid UTF-8 — return raw bytes
        # and decode with errors='replace' so the stream doesn't abort.
        conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
        # ── 1. People without floruit period ───────────────────────────
        n_no_flo = conn.execute(
            "SELECT COUNT(*) FROM individuals_floruit_period "
            "WHERE floruit_period_start IS NULL"
        ).fetchone()[0]
        n_with_flo = conn.execute(
            "SELECT COUNT(*) FROM individuals_floruit_period "
            "WHERE floruit_period_start IS NOT NULL"
        ).fetchone()[0]

        print(f"[no floruit] {n_no_flo:,}   [with floruit] {n_with_flo:,}")

        no_flo_occ = stream_counter(
            conn,
            """
            SELECT i.occupations_en
            FROM individuals i
            JOIN individuals_floruit_period f USING(wikidata_id)
            WHERE f.floruit_period_start IS NULL
            """,
            "no-floruit occupations",
            n_no_flo,
        )
        with_flo_occ = stream_counter(
            conn,
            """
            SELECT i.occupations_en
            FROM individuals i
            JOIN individuals_floruit_period f USING(wikidata_id)
            WHERE f.floruit_period_start IS NOT NULL
            """,
            "with-floruit occupations",
            n_with_flo,
        )
        no_flo_coc = stream_counter(
            conn,
            """
            SELECT i.country_of_citizenship_en
            FROM individuals i
            JOIN individuals_floruit_period f USING(wikidata_id)
            WHERE f.floruit_period_start IS NULL
            """,
            "no-floruit citizenship",
            n_no_flo,
        )
        with_flo_coc = stream_counter(
            conn,
            """
            SELECT i.country_of_citizenship_en
            FROM individuals i
            JOIN individuals_floruit_period f USING(wikidata_id)
            WHERE f.floruit_period_start IS NOT NULL
            """,
            "with-floruit citizenship",
            n_with_flo,
        )

        # ── 2. People without polity ──────────────────────────────────
        n_no_pol = conn.execute(
            """
            SELECT COUNT(*) FROM individuals i
            LEFT JOIN individuals_cliopatria c USING(wikidata_id)
            WHERE c.wikidata_id IS NULL
            """
        ).fetchone()[0]
        n_with_pol = conn.execute("SELECT COUNT(*) FROM individuals_cliopatria").fetchone()[0]
        print(f"[no polity ] {n_no_pol:,}   [with polity ] {n_with_pol:,}")

        no_pol_occ = stream_counter(
            conn,
            """
            SELECT i.occupations_en
            FROM individuals i
            LEFT JOIN individuals_cliopatria c USING(wikidata_id)
            WHERE c.wikidata_id IS NULL
            """,
            "no-polity occupations",
            n_no_pol,
        )
        with_pol_occ = stream_counter(
            conn,
            """
            SELECT i.occupations_en
            FROM individuals i
            JOIN individuals_cliopatria c USING(wikidata_id)
            """,
            "with-polity occupations",
            n_with_pol,
        )

        # Year distribution for no-polity people (use floruit_year if any,
        # else birth_year)
        years_df = pd.read_sql_query(
            """
            SELECT COALESCE(f.floruit_year, f.birth_year) AS year,
                   CASE WHEN c.wikidata_id IS NULL THEN 0 ELSE 1 END AS has_polity
            FROM individuals_floruit_period f
            LEFT JOIN individuals_cliopatria c USING(wikidata_id)
            WHERE COALESCE(f.floruit_year, f.birth_year) IS NOT NULL
            """,
            conn,
        )

    # ── Build comparative share tables ─────────────────────────────────
    def share_table(missing: Counter, present: Counter, n_miss: int, n_pres: int) -> pd.DataFrame:
        keys = set(missing) | set(present)
        rows = []
        for k in keys:
            m = missing.get(k, 0)
            p = present.get(k, 0)
            rows.append({
                "label": k,
                "miss_share": m / n_miss if n_miss else 0,
                "pres_share": p / n_pres if n_pres else 0,
                "miss_count": m,
                "pres_count": p,
            })
        df = pd.DataFrame(rows)
        df["lift"] = df["miss_share"] / df["pres_share"].replace(0, pd.NA)
        return df.sort_values("miss_count", ascending=False).head(TOP_N)

    occ_no_flo = share_table(no_flo_occ, with_flo_occ, n_no_flo, n_with_flo)
    coc_no_flo = share_table(no_flo_coc, with_flo_coc, n_no_flo, n_with_flo)
    occ_no_pol = share_table(no_pol_occ, with_pol_occ, n_no_pol, n_with_pol)

    print("\n── Top occupations among NO-FLORUIT individuals ──")
    print(occ_no_flo[["label", "miss_count", "miss_share", "pres_share", "lift"]].to_string(index=False))
    print("\n── Top citizenships among NO-FLORUIT individuals ──")
    print(coc_no_flo[["label", "miss_count", "miss_share", "pres_share", "lift"]].to_string(index=False))
    print("\n── Top occupations among NO-POLITY individuals ──")
    print(occ_no_pol[["label", "miss_count", "miss_share", "pres_share", "lift"]].to_string(index=False))

    # ── Plot ──────────────────────────────────────────────────────────
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    def grouped_bar(ax, df: pd.DataFrame, title: str) -> None:
        labels = df["label"].tolist()
        y = range(len(labels))
        ax.barh(
            [v - 0.2 for v in y], df["miss_share"] * 100,
            height=0.4, color="#c0392b", label="missing",
        )
        ax.barh(
            [v + 0.2 for v in y], df["pres_share"] * 100,
            height=0.4, color="#2b3a55", label="present",
        )
        ax.set_yticks(list(y))
        ax.set_yticklabels(labels, fontsize=9)
        ax.invert_yaxis()
        ax.set_xlabel("share within group (%)")
        ax.set_title(title, fontsize=10)
        ax.legend(loc="lower right", fontsize=8)
        ax.grid(axis="x", alpha=0.25, linewidth=0.5)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)

    grouped_bar(axes[0, 0], occ_no_flo, "No-floruit — top occupations  (missing vs present)")
    grouped_bar(axes[0, 1], coc_no_flo, "No-floruit — top citizenships  (missing vs present)")
    grouped_bar(axes[1, 0], occ_no_pol, "No-polity — top occupations  (missing vs present)")

    # Year histogram (no-polity vs with-polity), 50-yr bins
    ax = axes[1, 1]
    bins = range(-1000, 2050, 50)
    ax.hist(
        years_df.loc[years_df.has_polity == 0, "year"], bins=bins,
        alpha=0.6, color="#c0392b", label="no polity", density=True,
    )
    ax.hist(
        years_df.loc[years_df.has_polity == 1, "year"], bins=bins,
        alpha=0.6, color="#2b3a55", label="with polity", density=True,
    )
    ax.set_xlabel("year (50-yr bins)")
    ax.set_ylabel("density")
    ax.set_title("No-polity vs with-polity — year distribution", fontsize=10)
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(axis="y", alpha=0.25, linewidth=0.5)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)

    fig.suptitle("Patterns in missing-floruit and missing-polity individuals", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out = Path(__file__).with_suffix(".png")
    fig.savefig(out, dpi=140)
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
