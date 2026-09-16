CREATE OR REPLACE VIEW individual_polity AS
SELECT
    enriched.entity.qid                        AS qid,
    enriched.entity.label_en                   AS who,
    enriched.entity.description                AS described_as,
    enriched.peak_productivity.start_year      AS at_work_from,
    enriched.peak_productivity.end_year        AS at_work_until,
    enriched.peak_productivity.assignation_method AS window_from,
    enriched.polity_count                      AS polities,
    match.polity.cliopatria_id                 AS polity_id,
    match.polity.name                          AS polity,
    match.years_spent_in_polity                AS years_in_polity,
    match.assignation_method                   AS matched_by
FROM individual_enriched enriched, unnest(enriched.polity) AS t(match);
