"""Active individuals per century: Western-only vs non-Western-only.

An individual counts as "Western-only" if every catalog or Wikipedia edition
that records them is classified as Western (and at least one such record
exists).  Likewise for non-Western-only.  We exclude `commons.wikimedia.org`,
`species.wikimedia.org`, `simple.wikipedia.org`, sister projects (wikisource,
wikiquote, etc.) and the placeholder `internationality` catalogs from the
classification — they are language/region neutral.

Active = bucketed by `floruit_year` into 100-year bins.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
from tqdm import tqdm

DB = Path(__file__).resolve().parents[2] / "data" / "humans_clean.sqlite3"
OUT = Path(__file__).resolve().parents[2] / "docs" / "active_western_vs_nonwestern.png"

WESTERN_COUNTRIES = {
    "United States", "Washington, D.C.", "Germany", "France", "Poland",
    "Netherlands", "Kingdom of the Netherlands", "United Kingdom", "Wales",
    "Italy", "Kingdom of Italy", "Spain", "Sweden", "Norway", "Finland",
    "Denmark", "Faroe Islands", "Austria", "Belgium", "Switzerland",
    "Portugal", "Czech Republic", "Slovakia", "Greece", "Hungary",
    "Ireland", "Canada", "Australia", "New Zealand", "Romania", "Croatia",
    "Serbia", "Slovenia", "Lithuania", "Latvia", "Estonia", "Bulgaria",
    "Iceland", "Luxembourg", "Liechtenstein", "Andorra", "Cyprus",
    "Vatican City", "Weimar Republic", "German Reich",
}

WESTERN_WIKI_LANGS = {
    "en", "de", "fr", "es", "it", "pt", "nl", "pl", "sv", "no", "nb", "nn",
    "fi", "da", "is", "fo", "ga", "gd", "cy", "kw", "gv", "br", "co", "oc",
    "ca", "eu", "gl", "ast", "an", "ext", "lad", "mwl", "rm", "fur", "lij",
    "lmo", "nap", "pms", "scn", "vec", "sc", "lb", "wa", "fy", "li", "nds",
    "vls", "frr", "stq", "dsb", "hsb", "ksh", "bar", "pdc", "pfl", "gsw",
    "frp", "csb", "szl", "sli", "sli", "cs", "sk", "sl", "hr", "bs", "sr",
    "sh", "mk", "bg", "ro", "mo", "hu", "et", "lv", "lt", "el", "grc", "la",
    "vec", "scn", "simple",
}

NON_WESTERN_WIKI_LANGS = {
    "ar", "arz", "ru", "uk", "be", "be-tarask", "kk", "ky", "uz", "tg",
    "tk", "mn", "ja", "zh", "zh-yue", "yue", "wuu", "hak", "lzh", "ko",
    "id", "ms", "jv", "su", "min", "ace", "vi", "th", "lo", "km", "my",
    "tr", "az", "azb", "ckb", "fa", "he", "ur", "pnb", "ps", "sd", "hi",
    "bn", "as", "or", "ta", "te", "ml", "kn", "mr", "gu", "pa", "ne",
    "si", "dv", "ka", "hy", "yi", "tl", "ceb", "war", "ig", "yo", "ha",
    "sw", "zu", "xh", "st", "sn", "ny", "rw", "lg", "tn", "ts", "ve",
    "nso", "ss", "om", "so", "ti", "am", "tw", "ee", "fon", "kg", "lua",
    "sg", "ln", "mg", "ckb", "kab", "sat", "bho", "mai", "new", "anp",
    "doi", "ks", "sa", "pi", "dty", "awa", "shn", "tcy", "kok",
}


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA cache_size=-500000")
    conn.execute("PRAGMA mmap_size=4000000000")

    print("Classifying catalogs…")
    cur = conn.execute("SELECT property_id, country_name FROM identifier_types")
    w_pid, nw_pid = set(), set()
    for pid, country in cur:
        if not country or country == "internationality":
            continue
        if country in WESTERN_COUNTRIES:
            w_pid.add(pid)
        else:
            nw_pid.add(pid)
    print(f"  western catalog property_ids : {len(w_pid):,}")
    print(f"  non-western catalog property_ids : {len(nw_pid):,}")

    conn.execute("DROP TABLE IF EXISTS temp.w_pids")
    conn.execute("DROP TABLE IF EXISTS temp.nw_pids")
    conn.execute("CREATE TEMP TABLE w_pids (pid TEXT PRIMARY KEY)")
    conn.execute("CREATE TEMP TABLE nw_pids (pid TEXT PRIMARY KEY)")
    conn.executemany("INSERT INTO w_pids VALUES (?)", [(p,) for p in w_pid])
    conn.executemany("INSERT INTO nw_pids VALUES (?)", [(p,) for p in nw_pid])

    print("Classifying Wikipedia editions…")
    cur = conn.execute("SELECT DISTINCT site FROM wikimedia_links")
    w_sites, nw_sites = set(), set()
    for (site,) in cur:
        if not site or not site.endswith(".wikipedia.org"):
            continue
        lang = site.split(".", 1)[0]
        if lang in {"commons", "species", "simple"}:
            continue
        if lang in WESTERN_WIKI_LANGS:
            w_sites.add(site)
        elif lang in NON_WESTERN_WIKI_LANGS:
            nw_sites.add(site)
    print(f"  western wikipedia sites : {len(w_sites):,}")
    print(f"  non-western wikipedia sites : {len(nw_sites):,}")

    conn.execute("DROP TABLE IF EXISTS temp.w_sites")
    conn.execute("DROP TABLE IF EXISTS temp.nw_sites")
    conn.execute("CREATE TEMP TABLE w_sites (site TEXT PRIMARY KEY)")
    conn.execute("CREATE TEMP TABLE nw_sites (site TEXT PRIMARY KEY)")
    conn.executemany("INSERT INTO w_sites VALUES (?)", [(s,) for s in w_sites])
    conn.executemany("INSERT INTO nw_sites VALUES (?)", [(s,) for s in nw_sites])

    print("Aggregating Western / non-Western signals per individual…")
    conn.execute("DROP TABLE IF EXISTS temp.signals")
    conn.execute(
        """
        CREATE TEMP TABLE signals AS
        SELECT wikidata_id,
               MAX(is_w)  AS has_w,
               MAX(is_nw) AS has_nw
        FROM (
            SELECT i.wikidata_id,
                   CASE WHEN wp.pid  IS NOT NULL THEN 1 ELSE 0 END AS is_w,
                   CASE WHEN nwp.pid IS NOT NULL THEN 1 ELSE 0 END AS is_nw
            FROM identifiers i
            LEFT JOIN w_pids  wp  ON i.property_id = wp.pid
            LEFT JOIN nw_pids nwp ON i.property_id = nwp.pid
            UNION ALL
            SELECT wl.wikidata_id,
                   CASE WHEN ws.site  IS NOT NULL THEN 1 ELSE 0 END,
                   CASE WHEN nws.site IS NOT NULL THEN 1 ELSE 0 END
            FROM wikimedia_links wl
            LEFT JOIN w_sites  ws  ON wl.site = ws.site
            LEFT JOIN nw_sites nws ON wl.site = nws.site
        )
        GROUP BY wikidata_id
        """
    )
    conn.execute("CREATE INDEX temp.idx_signals ON signals(wikidata_id)")

    print("Counting active individuals per century…")
    rows = conn.execute(
        """
        SELECT (CAST(fp.floruit_year AS INTEGER) / 100) * 100 AS century,
               SUM(CASE WHEN s.has_w  = 1 AND s.has_nw = 0 THEN 1 ELSE 0 END) AS w_only,
               SUM(CASE WHEN s.has_nw = 1 AND s.has_w  = 0 THEN 1 ELSE 0 END) AS nw_only
        FROM individuals_floruit_period fp
        JOIN signals s ON fp.wikidata_id = s.wikidata_id
        WHERE fp.floruit_year IS NOT NULL
          AND fp.floruit_year BETWEEN -800 AND 2000
        GROUP BY century
        ORDER BY century
        """
    ).fetchall()
    conn.close()

    centuries = np.array([r[0] for r in rows])
    w_only = np.array([r[1] for r in rows])
    nw_only = np.array([r[2] for r in rows])
    print(f"  {len(centuries)} century buckets")
    print(f"  total western-only : {w_only.sum():,}")
    print(f"  total non-western-only : {nw_only.sum():,}")

    # plot
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=140)
    ax.plot(centuries, w_only, color="#2171b5", lw=1.8, marker="o", ms=3.5,
            label="Western catalog")
    ax.plot(centuries, nw_only, color="#b5542a", lw=1.8, marker="s", ms=3.5,
            label="Non-Western catalog")
    ax.set_yscale("log")
    ax.set_xlabel("Century (floruit)", fontsize=11)
    ax.set_ylabel("Active individuals (log)", fontsize=11)
    ax.set_title("Active individuals over time, by exclusive catalog/Wikipedia coverage",
                 fontsize=12)
    ax.grid(axis="y", alpha=0.18, ls="--")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(
        lambda x, _: f"{int(x)} BCE" if x < 0 else f"{int(x)} CE"))
    ax.legend(frameon=False, fontsize=10, loc="upper left")
    fig.tight_layout()
    fig.savefig(OUT, bbox_inches="tight")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
