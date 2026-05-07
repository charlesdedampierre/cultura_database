"""Export the list of individuals with no date (after every recovery step) but
with at least one Wikipedia page (any language) to a CSV."""
import time
import duckdb

DB  = "../data/humans_clean.sqlite3"
OUT = "../data/individuals_no_date_with_wikipedia.csv"

con = duckdb.connect()
con.execute("INSTALL sqlite; LOAD sqlite;")
con.execute(f"ATTACH '{DB}' AS hc (TYPE SQLITE, READ_ONLY);")

NO_DATE = """
    i.birthdate IS NULL
AND i.deathdate IS NULL
AND i.floruit_date IS NULL
AND i.floruit_year IS NULL
AND i.dates_in_description IS NULL
AND COALESCE(i.birthdate_in_description, 0) = 0
AND COALESCE(i.deathdate_in_description, 0) = 0
AND COALESCE(i.floruit_year_in_description, 0) = 0
AND i.birthdate_from_CV IS NULL
AND i.deathdate_from_CV IS NULL
AND i.works_period IS NULL
"""

# Per individual: count Wikipedia (any language) pages and pick a representative URL
# (English first if available, else any).
SQL = f"""
COPY (
    WITH wp AS (
        SELECT
            wikidata_id,
            COUNT(*) FILTER (WHERE site LIKE '%.wikipedia.org')                 AS wikipedia_pages_count,
            MAX(url)  FILTER (WHERE site = 'en.wikipedia.org')                  AS en_wikipedia_url,
            MAX(site) FILTER (WHERE site LIKE '%.wikipedia.org')                AS sample_wikipedia_site,
            MAX(url)  FILTER (WHERE site LIKE '%.wikipedia.org')                AS sample_wikipedia_url
        FROM hc.wikimedia_links
        WHERE site LIKE '%.wikipedia.org'
        GROUP BY wikidata_id
        HAVING COUNT(*) >= 1
    )
    SELECT
        i.wikidata_id,
        i.name_en,
        i.description_en,
        i.gender,
        i.country_of_citizenship_en,
        i.occupations_en,
        i.wikimedia_links_count,
        wp.wikipedia_pages_count,
        wp.en_wikipedia_url,
        COALESCE(wp.en_wikipedia_url, wp.sample_wikipedia_url) AS any_wikipedia_url,
        wp.sample_wikipedia_site
    FROM hc.individuals i
    JOIN wp USING (wikidata_id)
    WHERE {NO_DATE}
    ORDER BY wp.wikipedia_pages_count DESC, i.wikidata_id
) TO '{OUT}' (HEADER, DELIMITER ',');
"""

t0 = time.time()
con.execute(SQL)
elapsed = time.time() - t0

n = con.execute(f"SELECT COUNT(*) FROM read_csv_auto('{OUT}')").fetchone()[0]
print(f"Wrote {n:,} rows to {OUT}  ({elapsed:.1f}s)")
