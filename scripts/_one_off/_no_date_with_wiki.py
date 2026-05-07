"""How many individuals with no date at all have at least one Wikipedia page."""

import duckdb
from tqdm.auto import tqdm

DB = "../data/humans_clean.sqlite3"

con = duckdb.connect()
con.execute("INSTALL sqlite; LOAD sqlite;")
con.execute(f"ATTACH '{DB}' AS hc (TYPE SQLITE, READ_ONLY);")

NO_DATE = """
    birthdate IS NULL
AND deathdate IS NULL
AND floruit_date IS NULL
AND floruit_year IS NULL
AND dates_in_description IS NULL
AND COALESCE(birthdate_in_description, 0) = 0
AND COALESCE(deathdate_in_description, 0) = 0
AND COALESCE(floruit_year_in_description, 0) = 0
AND birthdate_from_CV IS NULL
AND deathdate_from_CV IS NULL
AND works_period IS NULL
"""

steps = [
    ("total individuals", "SELECT COUNT(*) FROM hc.individuals"),
    (
        "with any date (after every recovery step)",
        f"SELECT COUNT(*) FROM hc.individuals WHERE NOT ({NO_DATE})",
    ),
    ("with NO date at all", f"SELECT COUNT(*) FROM hc.individuals WHERE {NO_DATE}"),
    (
        "no-date AND wikimedia_links_count > 0  (any Wikimedia project)",
        f"SELECT COUNT(*) FROM hc.individuals WHERE {NO_DATE} AND wikimedia_links_count > 0",
    ),
    (
        "no-date AND >=1 Wikipedia page (any language)",
        f"""SELECT COUNT(DISTINCT i.wikidata_id)
         FROM hc.individuals i JOIN hc.wikimedia_links wl USING (wikidata_id)
         WHERE wl.site LIKE '%.wikipedia.org' AND ({NO_DATE.replace('birthdate', 'i.birthdate').replace('deathdate', 'i.deathdate').replace('floruit_date','i.floruit_date').replace('floruit_year','i.floruit_year').replace('dates_in_description','i.dates_in_description').replace('birthdate_in_description','i.birthdate_in_description').replace('deathdate_in_description','i.deathdate_in_description').replace('floruit_year_in_description','i.floruit_year_in_description').replace('birthdate_from_CV','i.birthdate_from_CV').replace('deathdate_from_CV','i.deathdate_from_CV').replace('works_period','i.works_period')})""",
    ),
    (
        "no-date AND >=1 English-Wikipedia page",
        f"""SELECT COUNT(DISTINCT i.wikidata_id)
         FROM hc.individuals i JOIN hc.wikimedia_links wl USING (wikidata_id)
         WHERE wl.site = 'en.wikipedia.org' AND ({NO_DATE.replace('birthdate', 'i.birthdate').replace('deathdate', 'i.deathdate').replace('floruit_date','i.floruit_date').replace('floruit_year','i.floruit_year').replace('dates_in_description','i.dates_in_description').replace('birthdate_in_description','i.birthdate_in_description').replace('deathdate_in_description','i.deathdate_in_description').replace('floruit_year_in_description','i.floruit_year_in_description').replace('birthdate_from_CV','i.birthdate_from_CV').replace('deathdate_from_CV','i.deathdate_from_CV').replace('works_period','i.works_period')})""",
    ),
]

results = {}
for label, q in tqdm(steps, desc="counting"):
    n = con.execute(q).fetchone()[0]
    results[label] = n
    print(f"{label:<60s}  {n:>12,}")

# Derived ratios
total = results["total individuals"]
n_any = results["with any date (after every recovery step)"]
n_no = results["with NO date at all"]
n_wiki_any = results["no-date AND >=1 Wikipedia page (any language)"]
n_wiki_en = results["no-date AND >=1 English-Wikipedia page"]
n_wm_any = results["no-date AND wikimedia_links_count > 0  (any Wikimedia project)"]

print()
print("=== SUMMARY ===")
print(f"total                                       {total:>12,}")
print(f"with any date                               {n_any:>12,}  ({n_any/total:.1%})")
print(f"no date at all                              {n_no:>12,}  ({n_no/total:.1%})")
print(
    f"  of which have any Wikimedia link          {n_wm_any:>12,}  ({n_wm_any/n_no:.1%})"
)
print(
    f"  of which have a Wikipedia page (any lang) {n_wiki_any:>12,}  ({n_wiki_any/n_no:.1%})"
)
print(
    f"  of which have an English-Wikipedia page   {n_wiki_en:>12,}  ({n_wiki_en/n_no:.1%})"
)
