"""Export a small sample of the simplified researcher dataset: individuals with a birth, a death, an active life, an occupation
and at least one Seshat-coded polity during the active life. One flat CSV:
- individuals.csv: one row per individual (dates, active life, occupations and the Seshat polities of each life stage, a marker with the Cliopatria id for a polity Seshat does not cover).
The sample is stratified by era of the start of the active life so that pre-modern individuals are visible, plus a stratum of individuals with century- or millennium-level dates:
their dates are century labels ('20th AC'), and their active life may be unknown (their polities then cover the century window of enrichment step 10)."""

import argparse
import sys
import tempfile
from pathlib import Path

import duckdb
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "1-datamodels"))
from datamodel_export import ExportedIndividualCSV

ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "data" / "cultura" / "cultura_enriched_v3.2.duckdb"
OUTPUT = ROOT / "data" / "exports" / "researcher_sample"
PER_ERA = 200
COARSE = 40  # individuals whose birth or death is known only to the century or millennium

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
CREATE TEMP MACRO stage_entries(matches) AS
    flatten(list_transform(matches, m -> CASE WHEN len(m.seshat) > 0
        THEN list_transform(m.seshat, one -> {{'id': one.id, 'name': coalesce(one.long_name, 'no Seshat name')}})
        ELSE [{{'id': 'no_seshat_polity', 'name': 'no Seshat polity associated with Cliopatria id ' || m.polity.cliopatria_id}}] END));
CREATE TEMP MACRO stage_polities(matches) AS
    list_filter(stage_entries(matches), (one, position) -> list_position(stage_entries(matches), one) = position);
CREATE TEMP MACRO cohort_metas(metas) AS list_filter(metas, m -> list_contains({COHORT_DOMAINS!r}, m));
CREATE TEMP MACRO all_metas(metas) AS list_filter(cohort_metas(metas), (m, position) -> list_position(cohort_metas(metas), m) = position);
CREATE TEMP MACRO year_precision(stated) AS CASE WHEN stated IN ('day', 'month') THEN 'year' ELSE stated END;
CREATE TEMP MACRO ordinal(n) AS n || CASE WHEN n % 100 IN (11, 12, 13) THEN 'th' WHEN n % 10 = 1 THEN 'st' WHEN n % 10 = 2 THEN 'nd' WHEN n % 10 = 3 THEN 'rd' ELSE 'th' END;
CREATE TEMP MACRO era_suffix(year) AS CASE WHEN year < 0 THEN ' BC' ELSE ' AC' END;
CREATE TEMP MACRO shown_year(d) AS CASE
    WHEN d.precision = 'century' THEN coalesce(d.coarse_label, ordinal(CAST(ceil(abs(d.year) / 100) AS BIGINT)) || era_suffix(d.year))
    WHEN d.precision = 'millennium' THEN coalesce(d.coarse_label, ordinal(CAST(ceil(abs(d.year) / 1000) AS BIGINT)) || ' millennium' || era_suffix(d.year))
    ELSE CAST(d.year AS VARCHAR)
END;
CREATE TEMP MACRO gender(qid) AS coalesce(MAP {GENDERS!r}[qid], qid);
"""

SAMPLE = f"""
CREATE TEMP TABLE candidate AS
SELECT
    entity.qid AS qid,
    CASE
        WHEN birth_date.precision IN ('century', 'millennium') OR death_date.precision IN ('century', 'millennium') THEN 'coarse dates'
        WHEN start_of_active_life.year < 1000 THEN 'before 1000'
        WHEN start_of_active_life.year < 1500 THEN '1000-1499'
        WHEN start_of_active_life.year < 1800 THEN '1500-1799'
        WHEN start_of_active_life.year < 1900 THEN '1800-1899'
        ELSE '1900 and after'
    END AS era
FROM individual_enriched
WHERE coalesce(CAST(birth_date.year AS VARCHAR), birth_date.coarse_label) IS NOT NULL
  AND coalesce(CAST(death_date.year AS VARCHAR), death_date.coarse_label) IS NOT NULL
  AND (start_of_active_life.year IS NOT NULL OR birth_date.precision IN ('century', 'millennium') OR death_date.precision IN ('century', 'millennium'))
  AND len(flatten(list_transform(active_life_polity, match -> match.seshat))) > 0;

CREATE TEMP TABLE picked AS
SELECT qid, era FROM candidate
QUALIFY row_number() OVER (PARTITION BY era ORDER BY hash(qid)) <= 2 * CASE WHEN era = 'coarse dates' THEN {COARSE} ELSE {PER_ERA} END;

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
    shown_year(sample.birth_date) AS birth_year,
    year_precision(sample.birth_date.precision) AS birth_precision,
    sample.birth_date.source AS birth_source,
    shown_year(sample.death_date) AS death_year,
    year_precision(sample.death_date.precision) AS death_precision,
    sample.death_date.source AS death_source,
    shown_year(sample.start_of_active_life) AS active_life_start,
    shown_year(sample.end_of_active_life) AS active_life_end,
    year_precision(sample.start_of_active_life.precision) AS active_life_start_precision,
    year_precision(sample.end_of_active_life.precision) AS active_life_end_precision,
    sample.start_of_active_life.source AS active_life_source,
    array_to_string(list_transform(individual.occupation, one -> label.of[one.entity.qid]), '{SEPARATOR}') AS occupations,
    main_meta(list_transform(individual.occupation, one -> label.meta[one.entity.qid])) AS occupation_domain,
    nullif(array_to_string(all_metas(list_transform(individual.occupation, one -> label.meta[one.entity.qid])), '{SEPARATOR}'), '') AS occupation_domains,
    individual.is_scientist AS is_scientist,
    individual.is_artist AS is_artist,
    array_to_string(list_transform(stage_polities(sample.pre_active_life_polity), one -> one.id), '{SEPARATOR}') AS pre_active_life_seshat_ids,
    array_to_string(list_transform(stage_polities(sample.pre_active_life_polity), one -> one.name), '{SEPARATOR}') AS pre_active_life_seshat_polities,
    array_to_string(list_transform(stage_polities(sample.active_life_polity), one -> one.id), '{SEPARATOR}') AS active_life_seshat_ids,
    array_to_string(list_transform(stage_polities(sample.active_life_polity), one -> one.name), '{SEPARATOR}') AS active_life_seshat_polities,
    array_to_string(list_transform(stage_polities(sample.post_active_life_polity), one -> one.id), '{SEPARATOR}') AS post_active_life_seshat_ids,
    array_to_string(list_transform(stage_polities(sample.post_active_life_polity), one -> one.name), '{SEPARATOR}') AS post_active_life_seshat_polities,
    len(list_distinct(list_transform(individual.work, one -> one.work_qid))) AS number_of_works
FROM sample
JOIN individual ON individual.entity.qid = sample.entity.qid
CROSS JOIN label
WHERE len(list_filter(individual.occupation, one -> label.of[one.entity.qid] IS NOT NULL)) > 0
QUALIFY row_number() OVER (PARTITION BY sample.era ORDER BY hash(sample.entity.qid)) <= CASE WHEN sample.era = 'coarse dates' THEN {COARSE} ELSE {PER_ERA} END
ORDER BY coalesce(sample.start_of_active_life.year, sample.birth_date.year, sample.death_date.year)
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

    rows = connection.execute(f"SELECT * FROM read_csv('{individuals}', all_varchar = true)")
    columns = [column[0] for column in rows.description]
    assert columns == list(ExportedIndividualCSV.model_fields), "the CSV's columns are not those of ExportedIndividualCSV"
    records = [dict(zip(columns, row)) for row in rows.fetchall()]
    for record in tqdm(records, desc="validate", unit=" rows"):
        ExportedIndividualCSV(**record)
    print(f"{len(records)} individuals written to {individuals}, all valid ExportedIndividualCSV rows")
    connection.close()


if __name__ == "__main__":
    main()
