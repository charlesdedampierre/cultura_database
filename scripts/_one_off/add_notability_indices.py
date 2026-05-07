"""Add three notability indices to the `individuals` table.

For each individual, three composite scores are stored:

  - notability_western     = wiki_western    + metadata_score + ids_western
  - notability_non_western = wiki_non_western + metadata_score + ids_non_western
  - notability_general     = sqrt(notability_western * notability_non_western)
    (equal-weight geometric mean — rewards balanced cross-cultural reach,
     penalises one-sided fame; zero on either side -> zero global score)

Components of the regional indices
----------------------------------
1. Wikipedia editions: distinct *.wikipedia.org sites per individual
   (commons / wikiquote / wikisource / wikinews / species / wikidata are
   excluded — they are not Wikipedia language editions).

2. Metadata completeness (0..3): one point each if `birthdate`, `gender`,
   `occupations_en` is present in `individuals`. Same value across the
   western and non-western indices because Wikidata is a single source.

3. External identifiers: count of rows in `identifiers` joined to
   `identifier_types`. The issuer's country (`identifier_types.country_name`)
   determines the western / non-western split.

Region buckets are listed in `WESTERN_*` / `NON_WESTERN_*` constants below
and follow the conventional cultural split (Western/Northern/Southern Europe
+ Anglosphere + Iberian Latin America = western; Eastern Slavic + Asia +
Middle East + Africa = non-western).

Compute path: DuckDB reads the source tables (per project rule: DuckDB
over sqlite3+pandas). Per-individual aggregates are written to a Parquet
file, then bulk-loaded into a sqlite temp table for a single UPDATE FROM.
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import duckdb
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "humans_clean.sqlite3"
STAGING_PARQUET = ROOT / "data" / "_notability_staging.parquet"


# ----------------------------------------------------------------------
# Region buckets
# ----------------------------------------------------------------------

# Wikipedia language tags considered "western" (Western/Central/Northern/
# Southern Europe + Anglosphere + Iberian-Latin-America-rooted languages +
# Latin/Esperanto/Ido/Interlingua/Volapük/Lingua Franca Nova as part of
# the western tradition). Anything not in either set is uncategorized
# and only contributes to `notability_general`.
WESTERN_LANGS = {
    # Germanic
    "en", "simple", "de", "nl", "af", "fy", "nds", "nds-nl", "li",
    "lb", "ksh", "bar", "stq", "pdc", "pfl", "vls", "zea",
    "sv", "no", "nn", "nb", "da", "fo", "is",
    # Romance
    "fr", "es", "it", "pt", "ca", "ro", "gl", "ast", "an", "oc",
    "co", "fur", "lij", "lmo", "nap", "scn", "sc", "vec", "pms",
    "rm", "lld", "wa", "frp", "ext", "mwl", "lad", "roa-rup",
    "roa-tara", "ie", "ia", "io", "eml", "pcd", "nrm", "gcr",
    "arpitan", "ppl", "pap", "lfn", "nov",
    # Celtic
    "ga", "gd", "cy", "br", "kw", "gv",
    # Baltic
    "lt", "lv", "ltg",
    # Finno-Ugric (Hungarian, Finnish, Estonian — culturally European)
    "fi", "et", "hu", "se", "smn", "fiu-vro", "vep",
    # Slavic European (Catholic / Latin-script)
    "pl", "cs", "sk", "sl", "hr", "bs", "sh", "csb", "szl", "hsb",
    "dsb", "rsk",
    # Greek + Albanian + Maltese + Basque
    "el", "pnt", "sq", "mt", "eu",
    # Constructed / scholarly Western tradition
    "la", "eo", "vo", "got", "ang", "cu", "jbo", "tok",
    # Misc Western European microlanguages
    "bat-smg", "lzh-classical",  # safety; lzh listed below as non-western
}

# Languages explicitly classified as non-western (East Slavic, Caucasus,
# Asia, Middle East, Africa, Pacific). Anything not in either set is
# uncategorized and contributes only to the general index.
NON_WESTERN_LANGS = {
    # East Slavic / former USSR Slavic / Orthodox-tradition Slavic
    "ru", "uk", "be", "be-tarask", "rue",
    "sr", "mk", "bg",  # Cyrillic-script Orthodox Slavic — east of dividing line
    # Caucasus
    "hy", "hyw", "ka", "xmf", "ab", "os", "ce", "av", "ady",
    "kbd", "inh", "lbe", "lez", "krc",
    # Turkic
    "tr", "az", "azb", "kk", "uz", "ky", "tt", "ba", "cv",
    "sah", "tk", "kaa", "crh", "tyv", "alt", "gag", "kge",
    # Iranian
    "fa", "ckb", "ku", "ps", "tg", "lrc", "glk", "mzn", "diq",
    # Semitic / Arabic varieties
    "ar", "arz", "arc", "he", "yi", "syl", "nqo", "ary",
    # Indic
    "hi", "bn", "ta", "te", "ml", "kn", "mr", "gu", "pa", "ur",
    "ne", "or", "as", "sa", "sd", "pi", "sat", "mai", "bh", "bpy",
    "skr", "pnb", "ks", "lah", "anp", "awa", "dty", "gom", "hif",
    "mni", "new", "rmy", "tcy",
    # East / Southeast Asia
    "zh", "zh-yue", "zh-min-nan", "zh-classical", "lzh", "wuu", "hak",
    "gan", "cdo", "nan", "cmn", "jam",
    "ja", "ko",
    "vi", "th", "lo", "km", "my", "shn", "mnw", "blk", "rki",
    "id", "ms", "jv", "su", "ban", "min", "ace", "bjn", "btm",
    "bug", "bcl", "ilo", "tl", "war", "ceb", "pam", "pag", "cbk-zam",
    "iba", "map-bms", "mad", "bbc", "tet", "tay", "trv", "szy",
    "ami", "pwn", "ann", "dtp", "atj", "bdr",
    # South / Central Asia minor
    "mn", "bo", "ug", "dv", "si", "dz",
    # Sub-Saharan Africa
    "sw", "ha", "ig", "yo", "am", "ti", "tig", "rw", "rn", "lg",
    "ny", "sn", "st", "tn", "ts", "ss", "ve", "xh", "zu", "nso",
    "nr", "nrm", "wo", "ee", "ak", "tw", "fon", "kg", "ki", "kab",
    "shi", "zgh", "so", "om", "lb-cong",  # placeholder
    "fat", "guc", "guw", "gur", "kbp", "kus", "dag", "dga", "din",
    "fon", "knc", "nia", "nup", "pcm", "sg", "tum", "yi-li",
    "bm", "ln", "ff", "kaj", "kcg", "igl", "mos", "mhr", "mrj",
    "myv", "udm", "koi", "kv", "mdf", "olo", "tum", "zu",
    # Indigenous Americas / Pacific (group with non-western for this split)
    "qu", "ay", "nah", "nv", "chr", "cr", "haw", "smn", "iu", "ik",
    "to", "ty", "fj", "sm", "mi", "na", "tpi", "bi", "ho", "pih",
    "chy", "srn", "xal", "om", "yue",
    # Misc
    "tly",
}

# Issuer countries from `identifier_types.country_name` considered western.
WESTERN_COUNTRIES = {
    "United States", "Germany", "France", "United Kingdom", "Italy",
    "Spain", "Netherlands", "Poland", "Czech Republic", "Sweden", "Norway",
    "Belgium", "Canada", "Switzerland", "Australia", "New Zealand",
    "Hungary", "Greece", "Slovenia", "Latvia", "Lithuania", "Estonia",
    "Slovakia", "Denmark", "Portugal", "Vatican City", "Finland",
    "Ireland", "Croatia", "Austria", "Andorra", "Iceland", "Luxembourg",
    "Liechtenstein", "Cyprus", "Malta", "Romania",
    # Latin America (Iberian-rooted, conventionally Western)
    "Brazil", "Mexico", "Argentina", "Chile", "Uruguay", "Peru",
    "Colombia",
    # South Africa is debated; the issuing institutions in practice are
    # western-style national libraries — keep it on the western side.
    "South Africa",
    # Historical / sub-national entries
    "Wales", "Washington, D.C.", "German Reich", "Kingdom of Italy",
    "Weimar Republic", "Kingdom of the Netherlands", "Faroe Islands",
}

NON_WESTERN_COUNTRIES = {
    "Russia", "Japan", "People's Republic of China", "Republic of China",
    "Taiwan", "South Korea", "India", "Iran", "Israel", "Turkey",
    "Indonesia", "Egypt", "Iraq", "Syria", "Lebanon", "Algeria",
    "Morocco", "Tanzania", "Cameroon", "Nigeria", "United Arab Emirates",
    "Kazakhstan", "Kyrgyzstan", "Uzbekistan", "Azerbaijan", "Armenia",
    "Georgia", "Ukraine", "Belarus", "Sri Lanka", "Albania", "Bulgaria",
    "Serbia", "Singapore", "Malaysia",
}

# `internationality` (e.g., VIAF, ISNI, Wikidata-internal) and NULL country
# are uncategorized: they count toward the general index only.


def now_clock() -> str:
    return time.strftime("%H:%M:%S")


def log(msg: str) -> None:
    print(f"[{now_clock()}] {msg}", flush=True)


def build_staging(con: duckdb.DuckDBPyConnection, sample_qids: set[str] | None) -> int:
    """Compute per-individual aggregates and write to STAGING_PARQUET.

    Returns row count.
    """
    sample_filter = ""
    if sample_qids is not None:
        con.execute("CREATE OR REPLACE TEMP TABLE _sample (wikidata_id TEXT PRIMARY KEY)")
        con.executemany("INSERT INTO _sample VALUES (?)", [(q,) for q in sample_qids])
        sample_filter = "WHERE i.wikidata_id IN (SELECT wikidata_id FROM _sample)"

    log("registering region lookup tables in DuckDB ...")
    con.execute("""
        CREATE OR REPLACE TEMP TABLE _western_langs (lang TEXT PRIMARY KEY);
        CREATE OR REPLACE TEMP TABLE _non_western_langs (lang TEXT PRIMARY KEY);
        CREATE OR REPLACE TEMP TABLE _western_countries (country TEXT PRIMARY KEY);
        CREATE OR REPLACE TEMP TABLE _non_western_countries (country TEXT PRIMARY KEY);
    """)
    con.executemany("INSERT INTO _western_langs VALUES (?)", [(x,) for x in WESTERN_LANGS])
    con.executemany("INSERT INTO _non_western_langs VALUES (?)", [(x,) for x in NON_WESTERN_LANGS])
    con.executemany("INSERT INTO _western_countries VALUES (?)", [(x,) for x in WESTERN_COUNTRIES])
    con.executemany("INSERT INTO _non_western_countries VALUES (?)", [(x,) for x in NON_WESTERN_COUNTRIES])

    log("aggregating Wikipedia editions per individual ...")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE _wiki_agg AS
        WITH base AS (
            SELECT
                wl.wikidata_id,
                wl.site,
                regexp_replace(wl.site, '\\.wikipedia\\.org$', '') AS lang
            FROM hc.wikimedia_links wl
            WHERE wl.site LIKE '%.wikipedia.org'
                {('AND wl.wikidata_id IN (SELECT wikidata_id FROM _sample)') if sample_qids is not None else ''}
        )
        SELECT
            wikidata_id,
            COUNT(DISTINCT site) AS wiki_total,
            COUNT(DISTINCT CASE WHEN lang IN (SELECT lang FROM _western_langs) THEN site END) AS wiki_western,
            COUNT(DISTINCT CASE WHEN lang IN (SELECT lang FROM _non_western_langs) THEN site END) AS wiki_non_western
        FROM base
        GROUP BY wikidata_id
    """)
    n_wiki = con.execute("SELECT COUNT(*) FROM _wiki_agg").fetchone()[0]
    log(f"  -> {n_wiki:,} individuals have at least one Wikipedia edition")

    log("aggregating external identifiers per individual ...")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE _ids_agg AS
        SELECT
            i.wikidata_id,
            COUNT(*) AS ids_total,
            COUNT(*) FILTER (WHERE it.country_name IN (SELECT country FROM _western_countries)) AS ids_western,
            COUNT(*) FILTER (WHERE it.country_name IN (SELECT country FROM _non_western_countries)) AS ids_non_western
        FROM hc.identifiers i
        LEFT JOIN hc.identifier_types it USING (property_id)
        {('WHERE i.wikidata_id IN (SELECT wikidata_id FROM _sample)') if sample_qids is not None else ''}
        GROUP BY i.wikidata_id
    """)
    n_ids = con.execute("SELECT COUNT(*) FROM _ids_agg").fetchone()[0]
    log(f"  -> {n_ids:,} individuals have at least one external identifier")

    log("computing metadata completeness from individuals ...")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE _meta AS
        SELECT
            i.wikidata_id,
            (CASE WHEN i.birthdate IS NOT NULL AND i.birthdate <> '' THEN 1 ELSE 0 END
           + CASE WHEN i.gender IS NOT NULL AND i.gender <> '' THEN 1 ELSE 0 END
           + CASE WHEN i.occupations_en IS NOT NULL AND i.occupations_en <> '' THEN 1 ELSE 0 END
            ) AS metadata_score
        FROM hc.individuals i
        {sample_filter}
    """)

    log("joining components into final notability indices ...")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE _notab AS
        SELECT
            m.wikidata_id,
            COALESCE(w.wiki_total, 0)        AS wiki_total,
            COALESCE(w.wiki_western, 0)      AS wiki_western,
            COALESCE(w.wiki_non_western, 0)  AS wiki_non_western,
            m.metadata_score,
            COALESCE(d.ids_total, 0)         AS ids_total,
            COALESCE(d.ids_western, 0)       AS ids_western,
            COALESCE(d.ids_non_western, 0)   AS ids_non_western,
            COALESCE(w.wiki_western, 0)     + m.metadata_score + COALESCE(d.ids_western, 0)      AS notability_western,
            COALESCE(w.wiki_non_western, 0) + m.metadata_score + COALESCE(d.ids_non_western, 0)  AS notability_non_western,
            sqrt(
                (COALESCE(w.wiki_western, 0)     + m.metadata_score + COALESCE(d.ids_western, 0))::DOUBLE
              * (COALESCE(w.wiki_non_western, 0) + m.metadata_score + COALESCE(d.ids_non_western, 0))::DOUBLE
            ) AS notability_general
        FROM _meta m
        LEFT JOIN _wiki_agg w USING (wikidata_id)
        LEFT JOIN _ids_agg  d USING (wikidata_id)
    """)
    n = con.execute("SELECT COUNT(*) FROM _notab").fetchone()[0]
    log(f"  -> {n:,} rows in final staging table")

    log(f"writing staging parquet to {STAGING_PARQUET} ...")
    con.execute(f"""
        COPY (SELECT wikidata_id, notability_general, notability_western, notability_non_western
              FROM _notab)
        TO '{STAGING_PARQUET}' (FORMAT PARQUET)
    """)
    return n


def ensure_columns(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(individuals)").fetchall()}
    spec = {
        "notability_western": "INTEGER NOT NULL DEFAULT 0",
        "notability_non_western": "INTEGER NOT NULL DEFAULT 0",
        "notability_general": "REAL NOT NULL DEFAULT 0",
    }
    for c, decl in spec.items():
        if c not in cols:
            conn.execute(f"ALTER TABLE individuals ADD COLUMN {c} {decl}")
            print(f"  added column individuals.{c}")
        else:
            print(f"  column individuals.{c} already exists")


def write_back(conn: sqlite3.Connection, n_rows: int) -> None:
    log("loading staging parquet into a sqlite temp table ...")
    # Read parquet via DuckDB, dump rows into a sqlite TEMP table in batches.
    dcon = duckdb.connect()
    dcon.execute(f"CREATE VIEW v AS SELECT * FROM read_parquet('{STAGING_PARQUET}')")

    conn.execute("""
        CREATE TEMP TABLE _notab (
            wikidata_id TEXT PRIMARY KEY,
            notability_general INTEGER,
            notability_western INTEGER,
            notability_non_western INTEGER
        )
    """)
    BATCH = 200_000
    cur = dcon.execute("SELECT wikidata_id, notability_general, notability_western, notability_non_western FROM v")
    pbar = tqdm(total=n_rows, desc="staging rows -> sqlite", unit="row")
    while True:
        rows = cur.fetchmany(BATCH)
        if not rows:
            break
        conn.executemany(
            "INSERT INTO _notab(wikidata_id, notability_general, notability_western, notability_non_western) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )
        pbar.update(len(rows))
    pbar.close()

    log("running UPDATE individuals FROM _notab ...")
    t0 = time.time()
    cur = conn.execute("""
        UPDATE individuals AS ind
        SET notability_general    = s.notability_general,
            notability_western    = s.notability_western,
            notability_non_western= s.notability_non_western
        FROM _notab s
        WHERE ind.wikidata_id = s.wikidata_id
    """)
    log(f"  UPDATE finished in {time.time() - t0:.1f}s; rows affected={cur.rowcount:,}")
    conn.commit()


def summarize(conn: sqlite3.Connection) -> None:
    log("summary statistics:")
    for col in ("notability_general", "notability_western", "notability_non_western"):
        row = conn.execute(
            f"SELECT MIN({col}), AVG({col}), MAX({col}), "
            f"  SUM(CASE WHEN {col} > 0 THEN 1 ELSE 0 END), COUNT(*) FROM individuals"
        ).fetchone()
        print(f"  {col}: min={row[0]}, mean={row[1]:.2f}, max={row[2]}, "
              f"non-zero={row[3]:,}/{row[4]:,}")


def main() -> int:
    if not DB_PATH.exists():
        print(f"database not found: {DB_PATH}", file=sys.stderr)
        return 1

    sample_qids: set[str] | None = None
    if "--sample" in sys.argv:
        idx = sys.argv.index("--sample")
        n = int(sys.argv[idx + 1])
        log(f"SAMPLE MODE: drawing {n} random wikidata_ids ...")
        with sqlite3.connect(DB_PATH) as c:
            sample_qids = {r[0] for r in c.execute(
                f"SELECT wikidata_id FROM individuals ORDER BY RANDOM() LIMIT {n}"
            ).fetchall()}
        log(f"  -> {len(sample_qids)} ids drawn")

    log("opening DuckDB and attaching humans_clean.sqlite3 (read-only) ...")
    dcon = duckdb.connect()
    dcon.execute("INSTALL sqlite_scanner; LOAD sqlite_scanner;")
    dcon.execute(f"ATTACH '{DB_PATH}' AS hc (TYPE sqlite, READ_ONLY);")

    n_rows = build_staging(dcon, sample_qids)
    dcon.close()

    log("opening sqlite3 for write ...")
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        ensure_columns(conn)

        if sample_qids is not None:
            log("SAMPLE MODE: limiting UPDATE to the sampled wikidata_ids")
            # Reset previous values for sampled ids so re-running benchmarks idempotently.
            ids = list(sample_qids)
            for i in range(0, len(ids), 1000):
                chunk = ids[i:i + 1000]
                placeholders = ",".join("?" * len(chunk))
                conn.execute(
                    f"UPDATE individuals SET notability_general=0, notability_western=0, "
                    f"notability_non_western=0 WHERE wikidata_id IN ({placeholders})",
                    chunk,
                )
            conn.commit()

        write_back(conn, n_rows)
        summarize(conn)
    finally:
        conn.close()

    if STAGING_PARQUET.exists() and "--keep-staging" not in sys.argv:
        STAGING_PARQUET.unlink()
        log(f"removed staging parquet {STAGING_PARQUET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
