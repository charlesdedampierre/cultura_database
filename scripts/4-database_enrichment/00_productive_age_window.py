"""Measure the productive age window, the quartiles of age at floruit globally and per occupation category, and write it to data/productive_age_window.csv."""

import csv
from datetime import date

import duckdb

from common import Enrichment, ROOT

SOURCE_DATABASE = ROOT / "data" / "cultura" / "humans_clean.duckdb"
CROSS_VERIFIED = ROOT / "data" / "similar_databases" / "cross-verified-database" / "cross-verified-database.utf8.csv.gz"
DATASET = ROOT / "data" / "productive_age_window.csv"

ENRICHMENT = Enrichment(
    reads=("IndividualWikidata.date_of_birth", "IndividualWikidata.floruit", "CrossVerifiedPerson.level1_main_occ"),
    writes=("data/productive_age_window.csv",),
    rule="The age at which people are at work, measured rather than assumed: for every individual whose birth year and Wikidata floruit (P1317) are both stated to the year, the age at that floruit, quartered. The first quartile and the third are the window, and the count beside them says how much weight it carries. Ages outside 0 to 100 are dropped. The categories are the cross-verified database's level1_main_occ; global is every individual, categorised or not.",
    answers=SOURCE_DATABASE,
)

MEASURE = f"""
WITH aged AS (
  SELECT wikidata_id,
         TRY_CAST(regexp_extract(floruit_date, '^(-?\\d+)', 1) AS INT)
       - TRY_CAST(regexp_extract(birthdate,   '^(-?\\d+)', 1) AS INT) AS age
  FROM individuals
  WHERE floruit_date IS NOT NULL AND floruit_precision >= 9
    AND birthdate IS NOT NULL AND birthdate_precision >= 9
),
categorised AS (
  SELECT aged.age, cross_verified.level1_main_occ AS category
  FROM aged
  LEFT JOIN read_csv('{CROSS_VERIFIED}', header=true, ignore_errors=true) AS cross_verified
    ON cross_verified.wikidata_code = aged.wikidata_id
  WHERE aged.age BETWEEN 0 AND 100
)
SELECT 'global' AS category, count(*) AS individuals,
       CAST(round(quantile_cont(age, 0.25)) AS INT) AS low_age,
       CAST(round(median(age)) AS INT) AS median_age,
       CAST(round(quantile_cont(age, 0.75)) AS INT) AS high_age
FROM categorised
UNION ALL
SELECT category, count(*),
       CAST(round(quantile_cont(age, 0.25)) AS INT),
       CAST(round(median(age)) AS INT),
       CAST(round(quantile_cont(age, 0.75)) AS INT)
FROM categorised WHERE category IS NOT NULL GROUP BY category
ORDER BY individuals DESC
"""

FIELDS = ("category", "individuals", "low_age", "median_age", "high_age", "measured_on")


def main():
    ENRICHMENT.announce()
    connection = duckdb.connect(str(SOURCE_DATABASE), read_only=True)
    measured = connection.execute(MEASURE).fetchall()
    connection.close()

    today = date.today().isoformat()
    with DATASET.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(FIELDS)
        for category, individuals, low, median, high in measured:
            writer.writerow([category, individuals, low, median, high, today])
            print(f"   {category:20} {individuals:>7,} individuals   age {low} to {high}, median {median}")

    print(f"\n{DATASET}")


if __name__ == "__main__":
    main()
