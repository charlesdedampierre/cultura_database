"""Count how many individuals each Wikipedia edition has a page on, and score each individual's cross-cultural notability from their Western and non-Western pages."""

import json

from tqdm import tqdm

from common import Enrichment, ROOT, as_json, open_database, provenance_column, rewrite_individual_enriched

SITELINK = Enrichment(
    reads=("IndividualSitelink.site_url",),
    writes=("Sitelink.number_of_articles",),
    rule="How many individuals in Cultura the edition has a page on.",
    answers=ROOT / "scripts" / "4-database_enrichment" / "06_individual_notability.py",
)

NOTABILITY = Enrichment(
    reads=("IndividualSitelink.site_url", "Sitelink.is_western"),
    writes=("IndividualEnriched.notability",),
    rule="The Wikipedia editions with a page on the individual, counted once each and split Western against non-Western on Sitelink.is_western; editions on neither list are left out of both counts. cross_cultural_score is the geometric mean of the two counts. An individual with no page scores 0.",
    inputs=("Sitelink.is_western",),
    answers=ROOT / "scripts" / "4-database_enrichment" / "06_individual_notability.py",
)


def fill_sitelink(connection):
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE sitelink AS
        WITH articles AS (
            SELECT site_url, count(DISTINCT qid) AS n
            FROM individual_sitelink JOIN individual ON individual.entity.qid = individual_sitelink.qid
            GROUP BY site_url
        )
        SELECT sitelink.* REPLACE (
            coalesce(articles.n, 0) AS number_of_articles,
            map_concat(sitelink.field_provenance, MAP {{'number_of_articles': ?::{provenance_column()}}}) AS field_provenance
        )
        FROM sitelink
        LEFT JOIN articles ON articles.site_url = sitelink.url
        """,
        [json.dumps(as_json(SITELINK.provenance()))],
    )


def fill_notability(connection):
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE counts AS
        SELECT individual_sitelink.qid,
               count(DISTINCT individual_sitelink.site_url) FILTER (WHERE sitelink.is_western) AS western,
               count(DISTINCT individual_sitelink.site_url) FILTER (WHERE NOT sitelink.is_western) AS non_western
        FROM individual_sitelink JOIN sitelink ON sitelink.url = individual_sitelink.site_url
        GROUP BY individual_sitelink.qid
        """
    )
    rewrite_individual_enriched(
        connection,
        f"""
        SELECT individual_enriched.* REPLACE (
            {{
                'number_of_western_editions': coalesce(counts.western, 0),
                'number_of_non_western_editions': coalesce(counts.non_western, 0),
                'cross_cultural_score': sqrt(coalesce(counts.western, 0) * coalesce(counts.non_western, 0))
            }} AS notability,
            map_concat(individual_enriched.field_provenance, MAP {{'notability': ?::{provenance_column()}}}) AS field_provenance
        )
        FROM individual_enriched LEFT JOIN counts ON counts.qid = individual_enriched.entity.qid
        WHERE {{inside}}
        """,
        [json.dumps(as_json(NOTABILITY.provenance()))],
    )


def report(connection):
    print("\neditions by is_western:")
    for label, editions, articles in connection.execute(
        "SELECT coalesce(is_western::VARCHAR, 'on neither list'), count(*), sum(number_of_articles) FROM sitelink GROUP BY 1 ORDER BY 1"
    ).fetchall():
        print(f"   {label:16} {editions:>5,} editions  {articles:>12,} pages")
    total, scored, top = connection.execute(
        "SELECT count(*), count(*) FILTER (WHERE notability.cross_cultural_score > 0), max(notability.cross_cultural_score) FROM individual_enriched"
    ).fetchone()
    print(f"\n{total:,} individuals, {scored:,} with a cross-cultural score above 0, highest {top or 0:.1f}")


def main():
    SITELINK.announce()
    NOTABILITY.announce()
    connection = open_database()
    connection.execute("SET enable_progress_bar = true; SET threads = 2; SET memory_limit = '8GB'")
    for step in tqdm((fill_sitelink, fill_notability), desc="notability", unit=" step"):
        connection.execute("BEGIN")
        step(connection)
        connection.execute("COMMIT")
    connection.execute("CHECKPOINT")
    report(connection)
    connection.close()


if __name__ == "__main__":
    main()
