"""Generate notebooks/20_cultura_vs_cross_verified.ipynb from scratch.

Two tables:
  Table 1 — Sources: Wikipedia + catalog presence (this script).
  Table 2 — Floruit & polity coverage (added later).
"""
from pathlib import Path
import nbformat as nbf

OUT = Path(__file__).resolve().parents[2] / "notebooks" / "20_cultura_vs_cross_verified.ipynb"

nb = nbf.v4.new_notebook()
nb.metadata = {
    "kernelspec": {
        "display_name": "Python (cultura_database)",
        "language": "python",
        "name": "cultura_database",
    },
    "language_info": {
        "codemirror_mode": {"name": "ipython", "version": 3},
        "file_extension": ".py",
        "mimetype": "text/x-python",
        "name": "python",
        "nbconvert_exporter": "python",
        "pygments_lexer": "ipython3",
        "version": "3.11.7",
    },
}

cells = []

cells.append(nbf.v4.new_markdown_cell(
    "# Cultura vs Cross-Verified — comparative tables"
))

cells.append(nbf.v4.new_code_cell(
    """# === notebook config (auto-managed; edit values, not the tag) ===
import random
import numpy as np

SEED = 42
random.seed(SEED)
np.random.seed(SEED)

# Data sources
DB_PATH = "../data/humans_clean.sqlite3"
CV_PATH = "../data/similar_databases/cross-verified-database/cross-verified-database.utf8.csv.gz"

# Figure style — minimal, Nature/Science publication standard
FIGSIZE = (8, 5)
DPI = 120
FONT_TITLE = 16
FONT_LABEL = 13
FONT_TICK = 11
FONT_LEGEND = 10

COLOR_PRIMARY = "#2171b5"
COLOR_SECONDARY = "#b5542a"
COLOR_NEUTRAL = "#7f7f7f"
COLOR_LIGHT = "#d9d9d9"
COLOR_ACCENT = "#6a9e3a"
PALETTE = [COLOR_PRIMARY, COLOR_SECONDARY, COLOR_ACCENT, COLOR_NEUTRAL, COLOR_LIGHT]

import matplotlib as _mpl
_mpl.rcParams.update({
    "figure.figsize": FIGSIZE,
    "figure.dpi": DPI,
    "axes.titlesize": FONT_TITLE,
    "axes.labelsize": FONT_LABEL,
    "xtick.labelsize": FONT_TICK,
    "ytick.labelsize": FONT_TICK,
    "legend.fontsize": FONT_LEGEND,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "font.family": "DejaVu Sans",
})
"""
))

cells.append(nbf.v4.new_markdown_cell(
    """## Western vs non-Western source classification

Reused across the notebook so both databases use identical definitions.

- **Western Wikipedia editions**: Western-European, Nordic, Latin-Slavic, Baltic, Greek, Latin, Esperanto.
- **Non-Western Wikipedia editions**: Arabic, Russian/Eastern-Slavic, Turkic, Persian, CJK, SE-Asian, Indic, Sub-Saharan-African, etc.
- **Western catalogs**: `identifier_types.country_name` ∈ Western set; `internationality` excluded.
- **Non-Western catalogs**: any other country.
"""
))

cells.append(nbf.v4.new_code_cell(
    """WESTERN_COUNTRIES = {
    'United States', 'Washington, D.C.', 'Germany', 'France', 'Poland',
    'Netherlands', 'Kingdom of the Netherlands', 'United Kingdom', 'Wales',
    'Italy', 'Kingdom of Italy', 'Spain', 'Sweden', 'Norway', 'Finland',
    'Denmark', 'Faroe Islands', 'Austria', 'Belgium', 'Switzerland',
    'Portugal', 'Czech Republic', 'Slovakia', 'Greece', 'Hungary',
    'Ireland', 'Canada', 'Australia', 'New Zealand', 'Romania', 'Croatia',
    'Serbia', 'Slovenia', 'Lithuania', 'Latvia', 'Estonia', 'Bulgaria',
    'Iceland', 'Luxembourg', 'Liechtenstein', 'Andorra', 'Cyprus',
    'Vatican City', 'Weimar Republic', 'German Reich',
}

WESTERN_WIKI_LANGS = {
    'en','de','fr','es','it','pt','nl','pl','sv','no','nb','nn','fi','da',
    'is','fo','ga','gd','cy','kw','gv','br','co','oc','ca','eu','gl','ast',
    'an','ext','lad','mwl','rm','fur','lij','lmo','nap','pms','scn','vec',
    'sc','lb','wa','fy','li','nds','vls','frr','stq','dsb','hsb','ksh','bar',
    'pdc','pfl','gsw','frp','csb','szl','cs','sk','sl','hr','bs','sr','sh',
    'mk','bg','ro','mo','hu','et','lv','lt','el','grc','la','simple','eo',
}

NON_WESTERN_WIKI_LANGS = {
    'ar','arz','ru','uk','be','be-tarask','kk','ky','uz','tg','tk','mn',
    'ja','zh','zh-yue','yue','wuu','hak','lzh','ko','id','ms','jv','su',
    'min','ace','vi','th','lo','km','my','tr','az','azb','ckb','fa','he',
    'ur','pnb','ps','sd','hi','bn','as','or','ta','te','ml','kn','mr','gu',
    'pa','ne','si','dv','ka','hy','yi','tl','ceb','war','ig','yo','ha','sw',
    'zu','xh','st','sn','ny','rw','lg','tn','ts','ve','nso','ss','om','so',
    'ti','am','tw','ee','fon','kg','lua','sg','ln','mg','kab','sat','bho',
    'mai','new','anp','doi','ks','sa','pi','dty','awa','shn','tcy','kok',
}
"""
))

# ---- Table 1: Sources ----
cells.append(nbf.v4.new_markdown_cell(
    """## Table 1 — Wikipedia & catalog content

Per-database counts of:
1. Unique individuals.
2. Individuals with at least one Wikipedia entry (any language).
3. Individuals in ≥ 1 of the **7 main Wikipedia editions used by Cross-Verified** (en, fr, de, es, it, pt, sv).
4. Individuals in Wikipedia **outside** the 7 main editions (≥ 1 Wiki article, none in the 7 main).
5. Individuals only in Wikidata (no Wikipedia article, no catalog identifier).
6. Individuals in Wikidata with ≥ 1 catalog (no Wikipedia article, ≥ 1 catalog identifier).
7. Individuals only in non-Western Wikipedia (no Western-Wiki edition, ≥ 1 non-Western edition).
8. Individuals only in non-Western catalogs (no Western catalog, ≥ 1 non-Western catalog).
9. Individuals present in Cultura but not in Cross-Verified (joined on Wikidata Q-id).
10. Individuals present in Cross-Verified but not in Cultura.

Cross-Verified is built from Wikipedia and does not carry external-catalog identifiers, so catalog-only and Wikidata-only rows are N/A for it.
"""
))

cells.append(nbf.v4.new_code_cell(
    """# 7 main Wikipedia editions used in the Cross-Verified study (Laouenan et al. 2022)
CV_SEVEN_LANGS = {'en', 'fr', 'de', 'es', 'it', 'pt', 'sv'}
CV_SEVEN_EDITIONS = {f'{l}wiki' for l in CV_SEVEN_LANGS}
"""
))

cells.append(nbf.v4.new_code_cell(
    """# ---- Cultura: pre-compute per-individual Wikipedia & catalog flags ----
import sqlite3, time

con = sqlite3.connect(DB_PATH)
con.execute("PRAGMA cache_size = -500000")

# Catalogs by country
w_pids, nw_pids = set(), set()
for pid, country in con.execute("SELECT property_id, country_name FROM identifier_types"):
    if not country or country == 'internationality':
        continue
    (w_pids if country in WESTERN_COUNTRIES else nw_pids).add(pid)

# Wikipedia sites by language
w_sites, nw_sites, all_wiki_sites, seven_sites = set(), set(), set(), set()
for (site,) in con.execute("SELECT DISTINCT site FROM wikimedia_links"):
    if not site or not site.endswith('.wikipedia.org'):
        continue
    lang = site.split('.', 1)[0]
    if lang in {'commons', 'species'}:
        continue
    all_wiki_sites.add(site)
    if lang in CV_SEVEN_LANGS:
        seven_sites.add(site)
    if lang in WESTERN_WIKI_LANGS:
        w_sites.add(site)
    elif lang in NON_WESTERN_WIKI_LANGS:
        nw_sites.add(site)

print(f"Western catalogs : {len(w_pids):,}   |  Non-Western : {len(nw_pids):,}")
print(f"Wikipedia editions — Western : {len(w_sites):,}, Non-Western : {len(nw_sites):,}, Total : {len(all_wiki_sites):,}, CV-7 main : {len(seven_sites):,}")

for tbl, vals in [("w_pids", w_pids), ("nw_pids", nw_pids),
                   ("w_sites", w_sites), ("nw_sites", nw_sites),
                   ("all_wiki_sites", all_wiki_sites),
                   ("seven_sites", seven_sites)]:
    con.execute(f"DROP TABLE IF EXISTS temp.{tbl}")
    con.execute(f"CREATE TEMP TABLE {tbl} (k TEXT PRIMARY KEY)")
    con.executemany(f"INSERT INTO {tbl} VALUES (?)", [(v,) for v in vals])

print("Aggregating per-individual catalog flags...")
t0 = time.time()
con.execute("DROP TABLE IF EXISTS temp.ind_cat")
con.execute(\"\"\"
    CREATE TEMP TABLE ind_cat AS
    SELECT i.wikidata_id,
           MAX(CASE WHEN wp.k  IS NOT NULL THEN 1 ELSE 0 END) AS w_cat,
           MAX(CASE WHEN nwp.k IS NOT NULL THEN 1 ELSE 0 END) AS nw_cat,
           1 AS has_cat
    FROM identifiers i
    LEFT JOIN w_pids  wp  ON i.property_id = wp.k
    LEFT JOIN nw_pids nwp ON i.property_id = nwp.k
    GROUP BY i.wikidata_id
\"\"\")
con.execute("CREATE INDEX temp.idx_ind_cat ON ind_cat(wikidata_id)")
print(f"  catalogs done in {time.time()-t0:.1f}s")

t0 = time.time()
con.execute("DROP TABLE IF EXISTS temp.ind_wiki")
con.execute(\"\"\"
    CREATE TEMP TABLE ind_wiki AS
    SELECT wl.wikidata_id,
           MAX(CASE WHEN ws.k  IS NOT NULL THEN 1 ELSE 0 END) AS w_wiki,
           MAX(CASE WHEN nws.k IS NOT NULL THEN 1 ELSE 0 END) AS nw_wiki,
           MAX(CASE WHEN aw.k  IS NOT NULL THEN 1 ELSE 0 END) AS has_wiki,
           MAX(CASE WHEN sv.k  IS NOT NULL THEN 1 ELSE 0 END) AS seven_wiki
    FROM wikimedia_links wl
    LEFT JOIN w_sites        ws  ON wl.site = ws.k
    LEFT JOIN nw_sites       nws ON wl.site = nws.k
    LEFT JOIN all_wiki_sites aw  ON wl.site = aw.k
    LEFT JOIN seven_sites    sv  ON wl.site = sv.k
    GROUP BY wl.wikidata_id
\"\"\")
con.execute("CREATE INDEX temp.idx_ind_wiki ON ind_wiki(wikidata_id)")
print(f"  wiki done in {time.time()-t0:.1f}s")
"""
))

cells.append(nbf.v4.new_code_cell(
    """# ---- Cultura counts ----
def q(sql):
    return con.execute(sql).fetchone()[0]

cultura_total = q("SELECT COUNT(*) FROM individuals")

cultura_has_wiki = q(\"\"\"
    SELECT COUNT(*) FROM ind_wiki WHERE has_wiki = 1
\"\"\")

# In ≥ 1 of the 7 main CV editions
cultura_in_seven = q("SELECT COUNT(*) FROM ind_wiki WHERE seven_wiki = 1")

# In Wikipedia but outside the 7 main editions
cultura_outside_seven = q(\"\"\"
    SELECT COUNT(*) FROM ind_wiki
    WHERE has_wiki = 1 AND seven_wiki = 0
\"\"\")

# "Only in Wikidata" = no Wikipedia article AND no catalog identifier
cultura_only_wikidata = q(\"\"\"
    SELECT COUNT(*) FROM individuals i
    LEFT JOIN ind_wiki w ON i.wikidata_id = w.wikidata_id
    LEFT JOIN ind_cat  c ON i.wikidata_id = c.wikidata_id
    WHERE COALESCE(w.has_wiki, 0) = 0
      AND COALESCE(c.has_cat,  0) = 0
\"\"\")

# In Wikidata + ≥ 1 catalog (no Wikipedia article)
cultura_wikidata_with_cat = q(\"\"\"
    SELECT COUNT(*) FROM individuals i
    LEFT JOIN ind_wiki w ON i.wikidata_id = w.wikidata_id
    LEFT JOIN ind_cat  c ON i.wikidata_id = c.wikidata_id
    WHERE COALESCE(w.has_wiki, 0) = 0
      AND COALESCE(c.has_cat,  0) = 1
\"\"\")

cultura_nw_wiki_only = q(\"\"\"
    SELECT COUNT(*) FROM ind_wiki
    WHERE w_wiki = 0 AND nw_wiki = 1
\"\"\")

cultura_nw_cat_only = q(\"\"\"
    SELECT COUNT(*) FROM ind_cat
    WHERE w_cat = 0 AND nw_cat = 1
\"\"\")

# Wikidata Q-id sets for overlap
cultura_qids = {r[0] for r in con.execute("SELECT wikidata_id FROM individuals")}
print(f"Cultura unique Q-ids : {len(cultura_qids):,}")
"""
))

cells.append(nbf.v4.new_code_cell(
    """# ---- Cross-Verified counts ----
import pandas as pd
from tqdm import tqdm

cv = pd.read_csv(CV_PATH, usecols=["wikidata_code", "list_wikipedia_editions"], low_memory=False)

cv_total = len(cv)
cv_has_wiki = cv["list_wikipedia_editions"].notna().sum()

W = WESTERN_WIKI_LANGS
NW = NON_WESTERN_WIKI_LANGS
SEVEN = CV_SEVEN_EDITIONS

def classify(s):
    if not isinstance(s, str) or not s:
        return (0, 0, 0)
    has_w = has_nw = has_seven = 0
    for tok in s.split('|'):
        if tok in SEVEN:
            has_seven = 1
        lang = tok[:-4] if tok.endswith('wiki') else tok
        if lang in W:
            has_w = 1
        elif lang in NW:
            has_nw = 1
    return (has_w, has_nw, has_seven)

tqdm.pandas(desc="CV wiki classify")
flags = cv["list_wikipedia_editions"].progress_apply(classify)
cv["w_wiki"]     = [a for a, _, _ in flags]
cv["nw_wiki"]    = [b for _, b, _ in flags]
cv["seven_wiki"] = [c for _, _, c in flags]

cv_nw_wiki_only    = int(((cv["w_wiki"] == 0) & (cv["nw_wiki"] == 1)).sum())
cv_in_seven        = int((cv["seven_wiki"] == 1).sum())
cv_outside_seven   = int(((cv["list_wikipedia_editions"].notna()) & (cv["seven_wiki"] == 0)).sum())

cv_qids = set(cv["wikidata_code"].dropna().astype(str))
print(f"Cross-Verified rows           : {cv_total:,}")
print(f"  with ≥1 Wikipedia edition   : {cv_has_wiki:,}")
print(f"  only in non-Western Wiki    : {cv_nw_wiki_only:,}")
print(f"  unique Q-ids                : {len(cv_qids):,}")
"""
))

cells.append(nbf.v4.new_code_cell(
    """# ---- Overlap ----
in_both       = cultura_qids & cv_qids
cultura_only  = cultura_qids - cv_qids
cv_only       = cv_qids - cultura_qids

print(f"In both                       : {len(in_both):,}")
print(f"In Cultura only (vs CV)       : {len(cultura_only):,}")
print(f"In Cross-Verified only        : {len(cv_only):,}")
"""
))

cells.append(nbf.v4.new_code_cell(
    """# ---- Build Table 1 ----
def fmt(n):
    return f"{n:,}" if isinstance(n, (int, np.integer)) else n

table1 = pd.DataFrame([
    {"Dimension": "Unique individuals",
     "Cultura": fmt(cultura_total),
     "Cross-Verified": fmt(cv_total)},
    {"Dimension": "With ≥ 1 Wikipedia entry",
     "Cultura": fmt(cultura_has_wiki),
     "Cross-Verified": fmt(int(cv_has_wiki))},
    {"Dimension": "In ≥ 1 of 7 main CV Wikipedias (en/fr/de/es/it/pt/sv)",
     "Cultura": fmt(cultura_in_seven),
     "Cross-Verified": fmt(cv_in_seven)},
    {"Dimension": "In Wikipedia but outside the 7 main editions",
     "Cultura": fmt(cultura_outside_seven),
     "Cross-Verified": fmt(cv_outside_seven)},
    {"Dimension": "Only in Wikidata (no Wiki, no catalog)",
     "Cultura": fmt(cultura_only_wikidata),
     "Cross-Verified": "N/A"},
    {"Dimension": "In Wikidata + ≥ 1 catalog (no Wiki)",
     "Cultura": fmt(cultura_wikidata_with_cat),
     "Cross-Verified": "N/A"},
    {"Dimension": "Only in non-Western Wikipedia",
     "Cultura": fmt(cultura_nw_wiki_only),
     "Cross-Verified": fmt(cv_nw_wiki_only)},
    {"Dimension": "Only in non-Western catalogs",
     "Cultura": fmt(cultura_nw_cat_only),
     "Cross-Verified": "N/A"},
    {"Dimension": "In Cultura but not in Cross-Verified",
     "Cultura": fmt(len(cultura_only)),
     "Cross-Verified": "—"},
    {"Dimension": "In Cross-Verified but not in Cultura",
     "Cultura": "—",
     "Cross-Verified": fmt(len(cv_only))},
])

table1.to_csv("tables/table1_cultura_vs_cross_verified_sources.csv", index=False)

(
    table1
    .style
    .hide(axis="index")
    .set_properties(**{"text-align": "left"})
    .set_table_styles([
        {"selector": "th", "props": [("text-align", "left"), ("font-weight", "600")]},
        {"selector": "td", "props": [("padding", "4px 12px")]},
    ])
)
"""
))

cells.append(nbf.v4.new_markdown_cell(
    """## Unified comparison — Cultura vs five reference databases

Single table covering all four core dimensions (population, polity, dates, occupation) **plus** the Wikipedia / catalog / overlap dimensions where they apply (Cultura vs Cross-Verified only).

- **Cross-Verified** — Laouenan et al. (2022), `data/similar_databases/cross-verified-database/`
- **Pantheon 2.0** — Yu et al., 2025 update CSV in `data/similar_databases/pantheon 2.0/`
- **HBR** — Nekoei & Sinn (2020), Human Biographical Record (numbers from Table 1 of the paper; data not redistributed, request pending)
- **Schich et al. 2014** — *Science* network framework of cultural history; FB (Freebase) sub-dataset, the one analyzed in the figures
- **Chaney (2024)** — *Modern Library Holdings and Historic City Growth*; VIAF-derived authors, Europe + MENA only

Em-dashes mark dimensions not represented in the source database. See `docs/comparison_databases_sources.md` for the verbatim quote / computation behind every cell.
"""
))

cells.append(nbf.v4.new_code_cell(
    """# ---- Cultura + Cross-Verified counts for the polity/date/occupation rows ----
con2 = sqlite3.connect(DB_PATH)
def q2(sql):
    return con2.execute(sql).fetchone()[0]

cultura_polity     = q2("SELECT COUNT(DISTINCT wikidata_id) FROM individuals_cliopatria")
cultura_floruit    = q2("SELECT COUNT(*) FROM individuals_floruit_period WHERE floruit_period_start IS NOT NULL")
cultura_occupation = q2("SELECT COUNT(*) FROM individuals WHERE occupations_en IS NOT NULL AND occupations_en != ''")
con2.close()

# Cross-Verified — reuse the cv DataFrame already loaded above; add the 3 fields
cv_extra = pd.read_csv(CV_PATH,
                        usecols=["citizenship_1_b", "birth", "death", "level1_main_occ"],
                        low_memory=False)
cv_citizen    = int(cv_extra["citizenship_1_b"].notna().sum())
cv_dates      = int((cv_extra["birth"].notna() | cv_extra["death"].notna()).sum())
cv_occupation = int((cv_extra["level1_main_occ"].notna() & (cv_extra["level1_main_occ"] != "Missing")).sum())
print(f"Cultura  polity={cultura_polity:,}  floruit={cultura_floruit:,}  occ={cultura_occupation:,}")
print(f"CV       citizen={cv_citizen:,}     dates={cv_dates:,}     occ={cv_occupation:,}")
"""
))

cells.append(nbf.v4.new_code_cell(
    """# ---- Compute Pantheon 2.0 counts directly from the CSV ----
p2 = pd.read_csv("../data/similar_databases/pantheon 2.0/person_2025_update.csv", low_memory=False)
p2_total      = len(p2)
p2_country    = int((p2["bplace_country"].notna() | p2["dplace_country"].notna()).sum())
p2_dates      = int((p2["birthyear"].notna() | p2["deathyear"].notna()).sum())
p2_occupation = int(p2["occupation"].notna().sum())
print(f"Pantheon 2.0  total={p2_total:,}  country={p2_country:,}  dates={p2_dates:,}  occ={p2_occupation:,}")

# ---- HBR figures: from Nekoei & Sinn (2020) Table 1 (Column 1 — full HBR) ----
HBR_TOTAL = 7_015_353
HBR_COUNTRY    = round(HBR_TOTAL * 0.7759)   # Country: 77.59 %
HBR_BIRTH      = round(HBR_TOTAL * 0.6043)   # Year of birth: 60.43 %
HBR_OCCUPATION = round(HBR_TOTAL * 0.7590)   # Occupation: 75.9 %
print(f"HBR (paper)  total={HBR_TOTAL:,}  country={HBR_COUNTRY:,}  birth={HBR_BIRTH:,}  occ={HBR_OCCUPATION:,}")

# ---- Schich et al. 2014: FB sub-dataset (the one used for the migration network) ----
SCHICH_FB_TOTAL = 120_211   # "120,211 individuals in the FB data set"
# By construction every FB individual has both birth and death dates.
print(f"Schich FB  total={SCHICH_FB_TOTAL:,}")

# ---- Chaney (2024): VIAF + supplementary sources after cleaning ----
CHANEY_TOTAL  = 537_247   # cleaned authority clusters (Europe + MENA, dates < 1800)
CHANEY_REGION = 486_179   # 470,189 European + 15,990 MENA, after deduplication & date check
CHANEY_DATES  = 537_247   # all kept by construction (numerical char in birth or death)
CHANEY_OCC    = 537_247   # all are "authors" by definition (single occupation)
print(f"Chaney  total={CHANEY_TOTAL:,}  region={CHANEY_REGION:,}")
"""
))

cells.append(nbf.v4.new_code_cell(
    """# ---- Build the single unified comparison table ----
def fnum(n):
    return f"{n:,}" if isinstance(n, (int, np.integer)) else n

DASH = "—"
NA   = "N/A"

# Combined Cultura non-Western source count (no Western wiki AND no Western catalog, ≥1 non-Western)
# Reuses `con` (still open) which holds the per-individual temp tables ind_wiki / ind_cat.
cultura_nw_combined = con.execute(\"\"\"
    SELECT COUNT(*) FROM individuals i
    LEFT JOIN ind_wiki w ON i.wikidata_id = w.wikidata_id
    LEFT JOIN ind_cat  c ON i.wikidata_id = c.wikidata_id
    WHERE COALESCE(w.w_wiki, 0) = 0
      AND COALESCE(c.w_cat,  0) = 0
      AND (COALESCE(w.nw_wiki, 0) = 1 OR COALESCE(c.nw_cat, 0) = 1)
\"\"\").fetchone()[0]
print(f"Cultura non-Western (wiki ∪ catalog) only : {cultura_nw_combined:,}")

# Each row: (dimension, Cultura, Cross-Verified, Pantheon 2, HBR, Schich, Chaney)
rows = [
    ("Total individuals",
        cultura_total,        cv_total,            p2_total,      HBR_TOTAL,      SCHICH_FB_TOTAL, CHANEY_TOTAL),
    ("With polity / citizenship",
        cultura_polity,       cv_citizen,          p2_country,    HBR_COUNTRY,    DASH,            CHANEY_REGION),
    ("With floruit / birth-or-death date",
        cultura_floruit,      cv_dates,            p2_dates,      HBR_BIRTH,      SCHICH_FB_TOTAL, CHANEY_DATES),
    ("With occupation",
        cultura_occupation,   cv_occupation,       p2_occupation, HBR_OCCUPATION, DASH,            CHANEY_OCC),
    ("Only in non-Western Wikipedia",
        cultura_nw_wiki_only, cv_nw_wiki_only,     DASH,          DASH,           DASH,            DASH),
    ("Only in non-Western catalogs",
        cultura_nw_cat_only,  NA,                  DASH,          DASH,           DASH,            DASH),
    ("Only in non-Western sources (wiki ∪ catalog)",
        cultura_nw_combined,  f"{cv_nw_wiki_only:,} (wiki only)", DASH, DASH,     DASH,            DASH),
    ("Number of individuals linked to a polity",
        cultura_polity,       NA,                  p2_country,    HBR_COUNTRY,    DASH,            CHANEY_REGION),
    ("Number of individuals with a date",
        cultura_floruit,      cv_dates,            p2_dates,      HBR_BIRTH,      SCHICH_FB_TOTAL, CHANEY_DATES),
    ("Number of individuals with an occupation",
        cultura_occupation,   cv_occupation,       p2_occupation, HBR_OCCUPATION, DASH,            CHANEY_OCC),
]

cols = ["Dimension", "Cultura", "Cross-Verified", "Pantheon 2", "HBR", "Schich et al 2014", "Chaney (2024)"]
table_full = pd.DataFrame([
    {cols[0]: r[0],
     cols[1]: fnum(r[1]),
     cols[2]: fnum(r[2]),
     cols[3]: fnum(r[3]),
     cols[4]: fnum(r[4]),
     cols[5]: fnum(r[5]),
     cols[6]: fnum(r[6])}
    for r in rows
])
table_full.to_csv("tables/table_full_comparison.csv", index=False)
table_full
"""
))

cells.append(nbf.v4.new_code_cell(
    """# ---- Publication-quality matplotlib table — single unified table ----
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

display_rows2 = rows
n_body = len(display_rows2)
row_h  = 0.55
fig_w  = 16.0
y_foot_top = 1.0
y_body_bot = y_foot_top
y_body_top = y_body_bot + n_body
y_head_top = y_body_top + 1
y_title    = y_head_top + 0.4
y_total    = y_title + 0.7
fig_h = y_total * row_h + 0.4

fig, ax = plt.subplots(figsize=(fig_w, fig_h))
ax.set_xlim(0, 1)
ax.set_ylim(0, y_total)
ax.axis('off')

# Column layout (right edges for numeric cols).
# Dimension column occupies 0..0.42; six numeric cols fill 0.42..1.00 in equal slots.
col_x_left = 0.005
n_cols = 6
left_block = 0.42
slot = (1.0 - left_block) / n_cols
col_edges  = [left_block + slot * (k + 1) - 0.005 for k in range(n_cols)]
col_headers = ["Cultura", "Cross-Verified", "Pantheon 2", "HBR", "Schich 2014", "Chaney 2024"]

# Title
ax.text(0.0, y_title + 0.1,
        "Table.  Cross-database comparison — six biographical datasets.",
        ha='left', va='bottom',
        fontsize=13, fontweight='bold', color='#111')

# Top double rule
ax.add_patch(Rectangle((0, y_head_top - 0.04), 1, 0.04, color='#111', lw=0))

# Header
y_head = y_body_top + 0.5
ax.text(col_x_left, y_head, "Dimension",
        ha='left',  va='center', fontsize=10.5, fontweight='bold', color='#111')
for x, h in zip(col_edges, col_headers):
    ax.text(x, y_head, h, ha='right', va='center',
            fontsize=10.5, fontweight='bold', color='#111')

# Header underline
ax.add_patch(Rectangle((0, y_body_top - 0.02), 1, 0.012, color='#666', lw=0))

# Body rows
for i, row in enumerate(display_rows2):
    dim = row[0]
    vals = row[1:]
    y = y_body_top - 0.5 - i
    ax.text(col_x_left, y, dim, ha='left', va='center', fontsize=9.5, color='#222')
    for x, v in zip(col_edges, vals):
        s = fnum(v)
        ax.text(x, y, s, ha='right', va='center',
                fontsize=9.5, color='#222',
                family='DejaVu Sans Mono')

# Bottom rule
ax.add_patch(Rectangle((0, y_body_bot - 0.02), 1, 0.025, color='#111', lw=0))

# Footnote
foot = (
    "Cultura, Cross-Verified, Pantheon 2.0: counts computed directly from the underlying data files "
    "(humans_clean.sqlite3 / *.csv.gz / person_2025_update.csv).  "
    "HBR: derived from Nekoei & Sinn (2020) Table 1 (n = 7,015,353; coverage shares applied).  "
    "Schich (2014): the FB sub-dataset used for the migration network — by construction every individual has both birth and death locations.  "
    "Chaney (2024): VIAF-derived authors after cleaning, Europe + MENA only.  "
    "Em-dashes mark dimensions not represented in the source database (see docs/comparison_databases_sources.md)."
)
ax.text(0.0, y_foot_top - 0.25, foot,
        ha='left', va='top', fontsize=8.5, color='#555', wrap=True)

plt.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
plt.savefig("tables/table_full_comparison.pdf", bbox_inches='tight')
plt.savefig("tables/table_full_comparison.png", dpi=300, bbox_inches='tight')
plt.show()
"""
))

nb.cells = cells
OUT.parent.mkdir(parents=True, exist_ok=True)
nbf.write(nb, OUT)
print("wrote", OUT)
