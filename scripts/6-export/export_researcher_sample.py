"""Export a small sample of the simplified researcher dataset: individuals with a birth, a death, an active life, an occupation
and at least one Seshat-coded polity during the active life. One flat CSV:
- individuals.csv: one row per individual (dates, active life, occupations, main Seshat polity and the Seshat polities of each life stage).
The sample is stratified by era of the start of the active life so that pre-modern individuals are visible."""

import argparse
import tempfile
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "data" / "cultura" / "cultura_enriched_v3.2.duckdb"
OUTPUT = ROOT / "data" / "exports" / "researcher_sample"
PER_ERA = 200

SEPARATOR = " | "
COHORT_DOMAINS = ["Culture", "Discovery/Science", "Leadership", "Sports/Games"]  # the occupational categories of the cohort analysis (01_notebooks_dates), 'Other' left out
GENDERS = {"Q6581097": "male", "Q6581072": "female", "Q1052281": "trans woman", "Q2449503": "trans man", "Q48270": "non-binary"}

LABELS = f"""
CREATE TEMP TABLE label AS
SELECT map(list(entity.qid), list(coalesce(entity.label_en, entity.label_non_en))) AS of,
       map(list(entity.qid), list(meta_occupation)) AS meta
FROM occupation;
CREATE TEMP MACRO main_meta(metas) AS
    list_max(list_transform(list_distinct(list_filter(metas, m -> list_contains({COHORT_DOMAINS!r}, m))), m -> {{
        'count': len(list_filter(metas, other -> other = m)), 'first': -list_position(metas, m), 'meta': m
    }})).meta;
CREATE TEMP MACRO main_seshat_match(matches) AS
    list_max(list_transform(list_filter(matches, m -> len(m.seshat) > 0), m -> {{'years': m.years_spent_in_polity, 'match': m}})).match;
CREATE TEMP TABLE seshat_span AS
SELECT map(list(cliopatria_id || '/' || seshat_id), list({{'start_year': start_year, 'end_year': end_year}})) AS of
FROM (
    SELECT polity.cliopatria_id, territory.seshat_id, min(territory.start_year) AS start_year, max(territory.end_year) AS end_year
    FROM polity, unnest(polity.territories) AS t(territory)
    WHERE territory.seshat_id IS NOT NULL
    GROUP BY ALL
);
CREATE TEMP MACRO main_seshat(match, active_start, active_end, span) AS
    list_max(list_transform(match.seshat, one -> {{
        'years': least(span[match.polity.cliopatria_id || '/' || one.id].end_year, active_end)
               - greatest(span[match.polity.cliopatria_id || '/' || one.id].start_year, active_start),
        'polity': one
    }})).polity;
CREATE TEMP MACRO stage_seshat(matches) AS
    list_filter(flatten(list_transform(matches, m -> m.seshat)), (one, position) -> list_position(flatten(list_transform(matches, m -> m.seshat)), one) = position);
CREATE TEMP MACRO year_precision(stated) AS CASE WHEN stated IN ('day', 'month') THEN 'year' ELSE stated END;
CREATE TEMP MACRO gender(qid) AS coalesce(MAP {GENDERS!r}[qid], qid);
"""

SAMPLE = f"""
CREATE TEMP TABLE candidate AS
SELECT
    entity.qid AS qid,
    CASE
        WHEN start_of_active_life.year < 1000 THEN 'before 1000'
        WHEN start_of_active_life.year < 1500 THEN '1000-1499'
        WHEN start_of_active_life.year < 1800 THEN '1500-1799'
        WHEN start_of_active_life.year < 1900 THEN '1800-1899'
        ELSE '1900 and after'
    END AS era
FROM individual_enriched
WHERE birth_date.year IS NOT NULL
  AND death_date.year IS NOT NULL
  AND start_of_active_life.year IS NOT NULL
  AND len(flatten(list_transform(active_life_polity, match -> match.seshat))) > 0;

CREATE TEMP TABLE picked AS
SELECT qid, era FROM candidate
QUALIFY row_number() OVER (PARTITION BY era ORDER BY hash(qid)) <= {PER_ERA * 2};

CREATE TEMP TABLE sample AS
SELECT individual_enriched.*, picked.era
FROM individual_enriched
JOIN picked ON picked.qid = individual_enriched.entity.qid;
"""

INDIVIDUALS = f"""
SELECT
    sample.entity.qid AS wikidata_id,
    coalesce(sample.entity.label_en, sample.entity.label_non_en) AS label,
    gender(individual.sex_or_gender) AS sex_or_gender,
    sample.birth_date.year AS birth_year,
    year_precision(sample.birth_date.precision) AS birth_precision,
    sample.birth_date.source AS birth_source,
    sample.death_date.year AS death_year,
    year_precision(sample.death_date.precision) AS death_precision,
    sample.death_date.source AS death_source,
    sample.start_of_active_life.year AS active_life_start,
    sample.end_of_active_life.year AS active_life_end,
    sample.start_of_active_life.source AS active_life_source,
    array_to_string(list_transform(individual.occupation, one -> label.of[one.entity.qid]), '{SEPARATOR}') AS occupations,
    main_meta(list_transform(individual.occupation, one -> label.meta[one.entity.qid])) AS occupation_domain,
    individual.is_scientist AS is_scientist,
    individual.is_artist AS is_artist,
    main.polity.id AS main_seshat_polity_id,
    main.polity.long_name AS main_seshat_polity,
    array_to_string(list_transform(stage_seshat(sample.pre_active_life_polity), one -> one.id), '{SEPARATOR}') AS pre_active_life_seshat_ids,
    array_to_string(list_transform(stage_seshat(sample.pre_active_life_polity), one -> coalesce(one.long_name, 'no Seshat name')), '{SEPARATOR}') AS pre_active_life_seshat_polities,
    array_to_string(list_transform(stage_seshat(sample.active_life_polity), one -> one.id), '{SEPARATOR}') AS active_life_seshat_ids,
    array_to_string(list_transform(stage_seshat(sample.active_life_polity), one -> coalesce(one.long_name, 'no Seshat name')), '{SEPARATOR}') AS active_life_seshat_polities,
    array_to_string(list_transform(stage_seshat(sample.post_active_life_polity), one -> one.id), '{SEPARATOR}') AS post_active_life_seshat_ids,
    array_to_string(list_transform(stage_seshat(sample.post_active_life_polity), one -> coalesce(one.long_name, 'no Seshat name')), '{SEPARATOR}') AS post_active_life_seshat_polities,
    len(list_distinct(list_transform(individual.work, one -> one.work_qid))) AS number_of_works
FROM sample
JOIN individual ON individual.entity.qid = sample.entity.qid
CROSS JOIN label
CROSS JOIN seshat_span
CROSS JOIN LATERAL (
    SELECT main_seshat(main_seshat_match(sample.active_life_polity), sample.start_of_active_life.year, sample.end_of_active_life.year, seshat_span.of) AS polity
) AS main
WHERE len(individual.occupation) > 0
QUALIFY row_number() OVER (PARTITION BY sample.era ORDER BY hash(sample.entity.qid)) <= {PER_ERA}
ORDER BY sample.start_of_active_life.year
"""



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DATABASE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    individuals = args.output / "individuals.csv"

    connection = duckdb.connect(str(args.database), read_only=True)
    connection.execute(f"SET memory_limit = '6GB'; SET threads = 4; SET temp_directory = '{tempfile.mkdtemp()}'")
    connection.execute(LABELS + SAMPLE)
    connection.execute(f"COPY ({INDIVIDUALS}) TO '{individuals}' (HEADER, DELIMITER ',')")

    print(connection.sql(f"SELECT count(*) AS individuals FROM read_csv('{individuals}')"))
    connection.close()


if __name__ == "__main__":
    main()
