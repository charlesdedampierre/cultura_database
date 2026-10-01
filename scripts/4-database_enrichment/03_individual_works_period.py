"""Give each individual the span of years covered by the publication and inception dates of their works."""

from common import DATABASE, Enrichment, ROOT, as_json, open_database, provenance_column, stage

ENRICHMENT = Enrichment(
    reads=("Individual.work", "Work.publication_date", "Work.inception"),
    writes=("Individual.works_period",),
    rule="The year of a work is its publication date where it has one and its inception otherwise. The period is the earliest and the latest of those years over every work credited to the individual. A work carrying neither date counts for nothing, so the span is narrower than a working life and empty for an individual none of whose works is dated.",
    answers=DATABASE,
)


def main():
    ENRICHMENT.announce()
    connection = open_database()
    stage(connection, "provenance", {"value": provenance_column()}, [{"value": as_json(ENRICHMENT.provenance())}])

    connection.execute("""
        CREATE OR REPLACE TEMP TABLE span AS
        SELECT link.qid AS qid,
               min(coalesce(work.publication_date.year, work.inception.year)) AS first_year,
               max(coalesce(work.publication_date.year, work.inception.year)) AS last_year
        FROM individual_work link
        JOIN work ON work.entity.qid = link.work_qid
        WHERE coalesce(work.publication_date.year, work.inception.year) IS NOT NULL
        GROUP BY 1
        """)

    connection.execute("""
        UPDATE individual SET
            works_period = {'first_year': span.first_year, 'last_year': span.last_year},
            field_provenance = map_concat(individual.field_provenance, MAP {'works_period': provenance.value})
        FROM span, provenance WHERE individual.entity.qid = span.qid
        """)

    filled, total = connection.execute("SELECT count(works_period), count(*) FROM individual").fetchone()
    dated, works = connection.execute("SELECT count(*) FILTER (coalesce(publication_date.year, inception.year) IS NOT NULL), count(*) FROM work").fetchone()
    print(f"{dated:,} of {works:,} works carry a date")
    print(f"individual.works_period set on {filled:,} of {total:,} individuals")
    connection.close()


if __name__ == "__main__":
    main()
