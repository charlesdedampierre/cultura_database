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

CREATE OR REPLACE VIEW individual_polity_unmatched AS
SELECT
    entity.qid                             AS qid,
    entity.label_en                        AS who,
    peak_productivity.start_year           AS at_work_from,
    peak_productivity.end_year             AS at_work_until,
    peak_productivity.assignation_method   AS window_from,
    individual.place_of_birth.entity.qid   AS birthplace,
    individual.place_of_death.entity.qid   AS deathplace,
    len(individual.country_of_citizenship) AS citizenships
FROM individual_enriched
JOIN individual USING (entity)
WHERE len(individual_enriched.polity) = 0;

CREATE OR REPLACE VIEW polity_population AS
SELECT
    polity.cliopatria_id      AS polity_id,
    polity.name               AS polity,
    polity.type               AS type,
    len(polity.territories)   AS territories,
    count(link.qid)           AS individuals,
    round(avg(link.years_in_polity), 1) AS average_years
FROM polity
LEFT JOIN individual_polity link ON link.polity_id = polity.cliopatria_id
GROUP BY 1, 2, 3, 4
ORDER BY individuals DESC;
