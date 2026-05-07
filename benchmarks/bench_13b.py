"""Benchmark notebook 13b end-to-end across three backends.

Backends compared:
  - sqlite_full     -> data/humans_clean.sqlite3
  - sqlite_reduced  -> data/humans_clean_reduced.sqlite3
  - duckdb          -> data/humans_clean.duckdb

The pipeline mirrors notebooks/13b_chinese_dynasties_floruit.ipynb cell by cell:
  1. fetch dynasty hulls (polities_cliopatria + polities_periods_cliopatria)
  2. per-dynasty counts (n_all, n_with_floruit) via per-dynasty queries
  3. pull every (individual, dynasty, floruit) tuple and run the polars
     precision-bucket reduction
  4. render the same two figures matplotlib produces and save them to PNGs

Each backend runs the full pipeline; we time wall-clock from start to finish.
"""

from __future__ import annotations

import argparse
import gc
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from matplotlib.ticker import PercentFormatter

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"

CHINESE_DYNASTIES = [
    "Shang Dynasty",
    "Zhou Dynasty",
    "Qin Dynasty",
    "Han Dynasty",
    "Xin Dynasty",
    "Western Jin",
    "Eastern Jin",
    "Liu Song Dynasty",
    "Liang Dynasty",
    "Chen Dynasty",
    "Northern Wei",
    "Eastern Wei",
    "Western Wei",
    "Northern Zhou",
    "Northern Qi",
    "Sui Dynasty",
    "Tang Dynasty",
    "Five Dynasties and Ten Kingdoms",
    "Northern Song",
    "Southern Song",
    "Liao Dynasty",
    "Western Xia",
    "Yuan Dynasty",
    "Ming Dynasty",
    "Qing Dynasty",
]

BAR_ALL_COLOR = "#bcd1e3"
BAR_FLO_COLOR = "#2f5b8a"
PREC_YEAR = "#1f3a5f"
PREC_DECADE = "#4c78a8"
PREC_CENTURY = "#9bbcd9"
PREC_DYNASTY = "#d8d2c3"


# ---------------------------------------------------------------------------
# Backend adapters
# ---------------------------------------------------------------------------
class SQLiteBackend:
    name = "sqlite"

    def __init__(self, db_path: Path):
        self.db_path = str(db_path)

    def connect(self):
        return sqlite3.connect(self.db_path)

    def fetch_periods(self, conn, names):
        placeholders = ",".join(["?"] * len(names))
        sql = f"""
            SELECT pc.name AS label,
                   MIN(pp.from_year) AS from_year,
                   MAX(pp.to_year)   AS to_year
            FROM polities_cliopatria pc
            JOIN polities_periods_cliopatria pp ON pc.id = pp.polity_id
            WHERE pc.name IN ({placeholders})
            GROUP BY pc.name
        """
        return pl.read_database(sql, conn, execute_options={"parameters": names})

    def count_dynasty(self, conn, name):
        sql = """
            SELECT
                COUNT(DISTINCT ic.wikidata_id)                                AS n_all,
                COUNT(DISTINCT CASE WHEN fp.floruit_period IS NOT NULL
                                    THEN ic.wikidata_id END)                  AS n_with_floruit
            FROM individuals_cliopatria ic
            LEFT JOIN individuals_floruit_period fp
                   ON ic.wikidata_id = fp.wikidata_id
            WHERE ';' || ic.polity_name || ';' LIKE ?
        """
        return conn.execute(sql, [f"%;{name};%"]).fetchone()

    def fetch_indiv_long(self, conn):
        sql = """
            SELECT ic.wikidata_id,
                   ic.polity_name,
                   fp.method,
                   fp.floruit_period,
                   fp.floruit_period_start AS fps,
                   fp.floruit_period_end   AS fpe
            FROM individuals_cliopatria ic
            LEFT JOIN individuals_floruit_period fp
                   ON ic.wikidata_id = fp.wikidata_id
            WHERE ic.polity_name IS NOT NULL
        """
        return pl.read_database(sql, conn)


class DuckDBBackend:
    name = "duckdb"

    def __init__(self, db_path: Path):
        self.db_path = str(db_path)

    def connect(self):
        return duckdb.connect(self.db_path, read_only=True)

    def fetch_periods(self, conn, names):
        placeholders = ",".join(["?"] * len(names))
        sql = f"""
            SELECT pc.name AS label,
                   MIN(pp.from_year) AS from_year,
                   MAX(pp.to_year)   AS to_year
            FROM polities_cliopatria pc
            JOIN polities_periods_cliopatria pp ON pc.id = pp.polity_id
            WHERE pc.name IN ({placeholders})
            GROUP BY pc.name
        """
        return conn.execute(sql, names).pl()

    def count_dynasty(self, conn, name):
        sql = """
            SELECT
                COUNT(DISTINCT ic.wikidata_id)                                AS n_all,
                COUNT(DISTINCT CASE WHEN fp.floruit_period IS NOT NULL
                                    THEN ic.wikidata_id END)                  AS n_with_floruit
            FROM individuals_cliopatria ic
            LEFT JOIN individuals_floruit_period fp
                   ON ic.wikidata_id = fp.wikidata_id
            WHERE ';' || ic.polity_name || ';' LIKE ?
        """
        return conn.execute(sql, [f"%;{name};%"]).fetchone()

    def fetch_indiv_long(self, conn):
        sql = """
            SELECT ic.wikidata_id,
                   ic.polity_name,
                   fp.method,
                   fp.floruit_period,
                   fp.floruit_period_start AS fps,
                   fp.floruit_period_end   AS fpe
            FROM individuals_cliopatria ic
            LEFT JOIN individuals_floruit_period fp
                   ON ic.wikidata_id = fp.wikidata_id
            WHERE ic.polity_name IS NOT NULL
        """
        return conn.execute(sql).pl()


# ---------------------------------------------------------------------------
# Pipeline (mirrors the notebook end-to-end)
# ---------------------------------------------------------------------------
def run_pipeline(backend, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    timings = {}

    t0 = time.perf_counter()
    conn = backend.connect()

    # --- cell `dynasties` ---
    t = time.perf_counter()
    periods = backend.fetch_periods(conn, CHINESE_DYNASTIES)
    order = {n: i for i, n in enumerate(CHINESE_DYNASTIES)}
    dyn_df = (
        periods.with_columns(
            pl.col("label").replace_strict(order, default=None).alias("_order")
        )
        .sort("_order")
        .drop("_order")
        .with_columns(
            ((pl.col("from_year") + pl.col("to_year")) / 2).alias("midpoint"),
            (pl.col("to_year") - pl.col("from_year")).alias("duration"),
        )
    )
    timings["periods"] = time.perf_counter() - t

    # --- cell `query` (25 sequential per-dynasty counts) ---
    t = time.perf_counter()
    counts = [backend.count_dynasty(conn, name) for name in dyn_df["label"].to_list()]
    counts = [(int(a or 0), int(b or 0)) for (a, b) in counts]
    dyn_df = dyn_df.with_columns(
        pl.Series("n_all", [c[0] for c in counts]),
        pl.Series("n_with_floruit", [c[1] for c in counts]),
    ).with_columns(
        (pl.col("n_all") - pl.col("n_with_floruit")).alias("n_missing"),
        pl.when(pl.col("n_all") > 0)
        .then((100 * pl.col("n_with_floruit") / pl.col("n_all")).round(1))
        .otherwise(None)
        .alias("pct_with_flo"),
    )
    timings["per_dynasty_counts"] = time.perf_counter() - t

    # --- cell `3452218d` (full join + polars precision reduction) ---
    t = time.perf_counter()
    indiv = backend.fetch_indiv_long(conn)
    timings["indiv_pull"] = time.perf_counter() - t

    try:
        conn.close()
    except Exception:
        pass

    t = time.perf_counter()
    dyn_labels = dyn_df["label"].to_list()
    indiv_long = (
        indiv.with_columns(pl.col("polity_name").str.split(";").alias("label"))
        .explode("label")
        .with_columns(pl.col("label").str.strip_chars())
        .filter(pl.col("label").is_in(dyn_labels))
    )
    indiv_long = indiv_long.with_columns(
        pl.when(pl.col("fps").is_null() | pl.col("fpe").is_null())
        .then(pl.lit("dynasty"))
        .when(pl.col("method").is_in(["birth_century", "death_century"]))
        .then(pl.lit("century"))
        .when((pl.col("fpe") - pl.col("fps")) <= 1)
        .then(pl.lit("year"))
        .when((pl.col("fpe") - pl.col("fps")) <= 30)
        .then(pl.lit("decade"))
        .when((pl.col("fpe") - pl.col("fps")) <= 100)
        .then(pl.lit("century"))
        .otherwise(pl.lit("dynasty"))
        .alias("precision")
    )
    PRECEDENCE = {"year": 0, "decade": 1, "century": 2, "dynasty": 3}
    indiv_long = (
        indiv_long.with_columns(
            pl.col("precision").replace_strict(PRECEDENCE).alias("_p")
        )
        .sort("_p")
        .unique(subset=["wikidata_id", "label"], keep="first", maintain_order=True)
    )

    prec_counts_pl = (
        indiv_long.group_by(["label", "precision"])
        .agg(pl.len().alias("n"))
        .pivot(values="n", index="label", on="precision")
        .fill_null(0)
    )
    for c in ["year", "decade", "century", "dynasty"]:
        if c not in prec_counts_pl.columns:
            prec_counts_pl = prec_counts_pl.with_columns(pl.lit(0).alias(c))

    prec_counts_pl = (
        pl.DataFrame({"label": dyn_labels})
        .join(prec_counts_pl, on="label", how="left")
        .with_columns(
            [pl.col(c).fill_null(0) for c in ["year", "decade", "century", "dynasty"]]
        )
        .with_columns(
            (
                pl.col("year")
                + pl.col("decade")
                + pl.col("century")
                + pl.col("dynasty")
            ).alias("total")
        )
    )
    import pandas as pd  # plotting boundary only

    prec_counts = prec_counts_pl.to_pandas().set_index("label")[
        ["year", "decade", "century", "dynasty", "total"]
    ]
    prec_share = (
        prec_counts[["year", "decade", "century", "dynasty"]]
        .div(prec_counts["total"].replace(0, np.nan), axis=0)
        .fillna(0)
    )
    timings["precision_reduce"] = time.perf_counter() - t

    # --- figure 1 (cell `fig`) ---
    t = time.perf_counter()
    fig, ax = plt.subplots(figsize=(17, 6.8))
    n = dyn_df.height
    xs = np.arange(n)
    bar_w = 0.38
    n_all_arr = dyn_df["n_all"].to_numpy()
    n_flo_arr = dyn_df["n_with_floruit"].to_numpy()
    labels_arr = dyn_df["label"].to_list()
    pct_arr = dyn_df["pct_with_flo"].to_list()
    y_max = float(n_all_arr.max()) * 1.15 if n_all_arr.max() > 0 else 1.0
    ax.bar(
        xs - bar_w / 2,
        n_all_arr,
        width=bar_w,
        color=BAR_ALL_COLOR,
        edgecolor="white",
        linewidth=0.6,
        label="All",
        zorder=2,
    )
    ax.bar(
        xs + bar_w / 2,
        n_flo_arr,
        width=bar_w,
        color=BAR_FLO_COLOR,
        edgecolor="white",
        linewidth=0.6,
        label="With floruit",
        zorder=2,
    )
    for i in range(n):
        pct_v = pct_arr[i]
        pct = "" if pct_v is None else f"{pct_v:.0f}%"
        ax.text(
            i - bar_w / 2,
            n_all_arr[i] + y_max * 0.012,
            f"{n_all_arr[i]:,}",
            ha="center",
            va="bottom",
            fontsize=9,
            color="#444",
        )
        ax.text(
            i + bar_w / 2,
            n_flo_arr[i] + y_max * 0.012,
            pct,
            ha="center",
            va="bottom",
            fontsize=9,
            color=BAR_FLO_COLOR,
            fontweight="bold",
        )
    ax.set_xticks(xs)
    ax.set_xticklabels(labels_arr, rotation=40, ha="right", fontsize=10)
    ax.set_xlim(-0.7, n - 0.3)
    ax.set_ylim(0, y_max)
    ax.legend(frameon=False, fontsize=11, loc="upper left")
    fig.tight_layout()
    fig.savefig(out_dir / f"fig1_{backend.name}.png", dpi=110)
    plt.close(fig)
    timings["fig1"] = time.perf_counter() - t

    # --- figure 2 (cell `ff8c8a6f`) ---
    t = time.perf_counter()
    fig, (ax_top, ax_bot) = plt.subplots(
        2,
        1,
        figsize=(17, 10),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 2]},
    )
    xs = np.arange(len(prec_counts))
    buckets = [
        ("year", "Year", PREC_YEAR),
        ("decade", "Decade", PREC_DECADE),
        ("century", "Century", PREC_CENTURY),
        ("dynasty", "Dynasty-only", PREC_DYNASTY),
    ]
    bottoms = np.zeros(len(prec_counts))
    for key, label, color in buckets:
        vals = prec_counts[key].to_numpy()
        ax_top.bar(
            xs,
            vals,
            bottom=bottoms,
            color=color,
            edgecolor="white",
            linewidth=0.5,
            label=label,
            zorder=2,
        )
        bottoms = bottoms + vals
    totals = prec_counts["total"].to_numpy()
    y_top = float(totals.max()) * 1.1 if totals.max() else 1.0
    for i, t_ in enumerate(totals):
        if t_ > 0:
            ax_top.text(
                i,
                t_ + y_top * 0.01,
                f"{int(t_):,}",
                ha="center",
                va="bottom",
                fontsize=8,
                color="#444",
            )
    ax_top.set_ylim(0, y_top * 1.05)
    ax_top.legend(frameon=False, fontsize=11, loc="upper left")
    bottoms = np.zeros(len(prec_share))
    for key, label, color in buckets:
        vals = prec_share[key].to_numpy()
        ax_bot.bar(
            xs,
            vals,
            bottom=bottoms,
            color=color,
            edgecolor="white",
            linewidth=0.5,
            zorder=2,
        )
        bottoms = bottoms + vals
    ax_bot.set_xticks(xs)
    ax_bot.set_xticklabels(prec_counts.index, rotation=40, ha="right", fontsize=10)
    ax_bot.set_xlim(-0.7, len(prec_counts) - 0.3)
    ax_bot.set_ylim(0, 1.0)
    ax_bot.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    fig.tight_layout()
    fig.savefig(out_dir / f"fig2_{backend.name}.png", dpi=110)
    plt.close(fig)
    timings["fig2"] = time.perf_counter() - t

    timings["total"] = time.perf_counter() - t0
    return timings, dyn_df, prec_counts


def run_backend(label: str, backend, out_dir: Path):
    print(f"\n=== {label} ({backend.db_path}) ===", flush=True)
    gc.collect()
    timings, dyn_df, prec_counts = run_pipeline(backend, out_dir / label)
    for k, v in timings.items():
        print(f"  {k:24s} {v:8.3f}s", flush=True)
    print(
        f"  rows: dynasties={dyn_df.height} "
        f"sum_n_all={int(dyn_df['n_all'].sum()):,} "
        f"sum_with_flo={int(dyn_df['n_with_floruit'].sum()):,}",
        flush=True,
    )
    return timings


def drop_os_cache():
    """Best-effort cold-cache for fair comparison; macOS `purge` requires sudo."""
    if sys.platform != "darwin":
        return False
    try:
        r = subprocess.run(["sudo", "-n", "purge"], capture_output=True, timeout=60)
        return r.returncode == 0
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--backend",
        choices=["all", "sqlite_full", "sqlite_reduced", "duckdb"],
        default="all",
    )
    ap.add_argument("--out", default=str(REPO / "benchmarks" / "out"))
    ap.add_argument(
        "--cold",
        action="store_true",
        help="try to drop OS page cache between runs (needs sudo -n purge)",
    )
    args = ap.parse_args()
    out_dir = Path(args.out)

    backends = {
        "sqlite_full": SQLiteBackend(DATA / "humans_clean.sqlite3"),
        "sqlite_reduced": SQLiteBackend(DATA / "humans_clean_reduced.sqlite3"),
        "duckdb": DuckDBBackend(DATA / "humans_clean.duckdb"),
    }
    order = (
        ["sqlite_full", "sqlite_reduced", "duckdb"]
        if args.backend == "all"
        else [args.backend]
    )

    results = {}
    for name in order:
        b = backends[name]
        if not Path(b.db_path).exists():
            print(f"!! skipping {name}: {b.db_path} not found", flush=True)
            continue
        if args.cold:
            ok = drop_os_cache()
            print(
                f"  cold-cache purge: {'ok' if ok else 'skipped (no sudo)'}", flush=True
            )
        results[name] = run_backend(name, b, out_dir)

    print("\n=== SUMMARY (total wall time) ===")
    for name, t in sorted(results.items(), key=lambda kv: kv[1]["total"]):
        print(f"  {name:18s} {t['total']:8.3f}s")


if __name__ == "__main__":
    main()
