# Cultura Database Schema

Complete documentation of all tables and columns in `data/humans_clean.duckdb`.

> **Engine:** DuckDB. Types below are the native DuckDB types as reported by
> `PRAGMA table_info` (`VARCHAR`, `BIGINT`, `INTEGER`, `DOUBLE`, `BOOLEAN`).
> Query this file with DuckDB or Polars (not `sqlite3`). Row counts are
> point-in-time snapshots and drift as the database is rebuilt.

The database has **18 base tables** (no views).

## Core Tables

### `individuals` (13,003,420 rows)

Main biographical data for all individuals. One row per `wikidata_id`.

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | VARCHAR | Wikidata identifier (e.g., Q937 for Albert Einstein) |
| `name_en` | VARCHAR | Full name in English |
| `description_en` | VARCHAR | Short Wikidata description |
| `birthdate` | VARCHAR | Date of birth (ISO format, negative years for BCE) |
| `birthdate_precision` | BIGINT | Precision: 11=day, 10=month, 9=year, 8=decade, 7=century |
| `deathdate` | VARCHAR | Date of death |
| `deathdate_precision` | BIGINT | Precision level |
| `country_of_citizenship_en` | VARCHAR | Semicolon-separated countries of citizenship |
| `birthcity_en` | VARCHAR | City of birth |
| `deathcity_en` | VARCHAR | City of death |
| `occupations_en` | VARCHAR | Semicolon-separated occupations |
| `wikimedia_links_count` | BIGINT | Number of Wikipedia pages across all languages |
| `gender` | VARCHAR | Gender |
| `identifiers_count` | BIGINT | Number of external database identifiers |
| `writing_language_name_en` | VARCHAR | Writing language(s) |
| `number_of_works` | BIGINT | Number of works in `works` table for this individual |
| `floruit_date` | VARCHAR | Floruit date from Wikidata P1317 (ISO format) |
| `floruit_precision` | BIGINT | Precision level for `floruit_date` |
| `floruit_year` | BIGINT | Floruit year derived from `individuals_floruit_period` |
| `dates_in_description` | VARCHAR | Year span parsed out of the Wikidata description (e.g. `1937-2016`) |
| `birthdate_in_description` | BIGINT | Birth year extracted from the description (NULL if none) |
| `deathdate_in_description` | BIGINT | Death year extracted from the description |
| `floruit_year_in_description` | BIGINT | Floruit year extracted from the description |
| `date_description` | VARCHAR | Raw date string found in the description (e.g. `1937-2016`) |
| `pantheon_2_db` | BIGINT | 1 if the individual is present in the Pantheon 2.0 dataset, else 0 |
| `cross_verified_db` | BIGINT | 1 if present in the cross-verified (CVDB) dataset, else 0 |
| `non_human` | BIGINT | 1 if flagged as a non-human entity (872 rows), else 0 |
| `works_period` | VARCHAR | Span of years the individual was producing works. Single year (e.g. `1946`) when first==last, else `min-max` (e.g. `1892-1964`). Per-work effective year = year of `works.publication_date` if present, else `works.inception_date`. NULL when none of the individual's works has a date. BCE preserves the leading `-` (e.g. `-558`). |
| `notability_western` | BIGINT | Western notability score (count of Western-language Wikipedia editions, 0–228) |
| `notability_non_western` | BIGINT | Non-Western notability score |
| `notability_general` | DOUBLE | Geometric mean of Western × non-Western notability — the project's canonical ranking metric (0–~282) |
| `birthdate_from_CV` | VARCHAR | Birth date sourced from the CV/biographical database (when available) |
| `deathdate_from_CV` | VARCHAR | Death date sourced from the CV/biographical database |
| `birthdate_from_life_expectancy` | VARCHAR | Birth date estimated via the life-expectancy model |
| `deathdate_from_life_expectancy` | VARCHAR | Death date estimated via the life-expectancy model |
| `life_expectancy_lookup_source` | VARCHAR | Which life-expectancy lookup was used: `birth_bin`, or `category+birth_bin:<Category>` (Leadership / Culture / Sports/Games / Discovery/Science / Other) |
| `life_expectancy_median_used` | DOUBLE | Median life-expectancy value applied for the estimate |
| `birthdate_from_wikipedia` | VARCHAR | Birth date scraped from Wikipedia |
| `deathdate_from_wikipedia` | VARCHAR | Death date scraped from Wikipedia |
| `floruit_from_wikipedia` | VARCHAR | Floruit date scraped from Wikipedia |
| `is_artist` | BOOLEAN | Artist flag. **Currently unpopulated (all NULL)** — use `individuals_cliopatria`/`occupations` rollups instead. |
| `is_scientist` | BOOLEAN | Scientist flag. **Currently unpopulated (all NULL).** |

### `individuals_keys` (13,002,897 rows)

Raw Wikidata Q-IDs for cross-references.

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | VARCHAR | Individual Wikidata ID |
| `birthcity_id` | VARCHAR | Birth city Wikidata ID |
| `deathcity_id` | VARCHAR | Death city Wikidata ID |
| `country_of_citizenship_ids` | VARCHAR | Semicolon-separated country-of-citizenship IDs |
| `occupations_ids` | VARCHAR | Semicolon-separated occupation IDs |
| `gender_id` | VARCHAR | Gender Wikidata ID |
| `writing_language_ids` | VARCHAR | Semicolon-separated language IDs |

### `individuals_floruit_period` (13,003,420 rows)

Per-individual floruit window with the method and source used to derive it.

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | VARCHAR | Individual Wikidata ID |
| `name_en` | VARCHAR | Individual name |
| `birthdate` | VARCHAR | Birth date (ISO format) |
| `birthdate_precision` | BIGINT | Birth date precision |
| `birth_year` | BIGINT | Birth year |
| `deathdate` | VARCHAR | Death date |
| `deathdate_precision` | BIGINT | Death date precision |
| `death_year` | BIGINT | Death year |
| `floruit_date` | VARCHAR | Floruit date (ISO format) |
| `floruit_precision` | BIGINT | Floruit date precision |
| `floruit_year` | BIGINT | Floruit year |
| `floruit_period` | VARCHAR | Period label (e.g., "1962-1987") |
| `floruit_period_start` | BIGINT | Start year of activity window |
| `floruit_period_end` | BIGINT | End year of activity window |
| `method` | VARCHAR | Derivation method: `birth_only_property`, `birth_death_property`, `works_span`, `works_single`, `under_30`, `birth_death_estimated_birth`, `floruit_description`, `no_data` |
| `source` | VARCHAR | Origin of the dates: `wikidata_property`, `works`, `life_expectancy`, `wikidata_description`, `cv_database`, `wikipedia`, `none` |
| `precision_class` | VARCHAR | Resolved precision bucket: `year`, `century`, `decade` |
| `estimated` | BIGINT | 1 if the window was estimated (life-expectancy model), else 0 |
| `works_period` | VARCHAR | Works-derived year span (mirrors `individuals.works_period`) |

### `individuals_cliopatria` (7,830,341 rows · 5,161,090 individuals)

Individual-to-historical-polity mapping (Cliopatria dataset). **Multi-polity:**
one row per (individual, polity) where the polity's period overlaps the
individual's floruit window. An individual whose floruit straddles a regime
change therefore appears under every overlapping polity.

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | VARCHAR | Individual Wikidata ID (NOT unique — multi-polity) |
| `name_en` | VARCHAR | Individual name |
| `polity_id` | BIGINT | Polity ID in `polities_cliopatria` |
| `polity_name` | VARCHAR | Historical polity (e.g., "Ottoman Empire") |
| `origin` | VARCHAR | Location source: `birthplace`, `deathplace`, `country_of_citizenship` |
| `matched_name` | VARCHAR | City or country-of-citizenship name matched |
| `matched_wikidata_id` | VARCHAR | Wikidata ID of matched entity |
| `method` | VARCHAR | `merge_with_polygon` or `merge_with_url` |
| `floruit_year` | INTEGER | Floruit year (midpoint or single year) |
| `floruit_period_start` | INTEGER | Start of floruit window |
| `floruit_period_end` | INTEGER | End of floruit window |
| `overlap_years` | INTEGER | Years of floruit window covered by this polity (sum across multiple periods of the same polity) |

**Cascade priority** (location-priority preserved from single-polity version,
multi-polity only on the temporal axis — see `docs/CLASSIFICATION_RULES.md`):

1. Phase 1 polygon: deathplace → birthplace → country_of_citizenship.
   First location that produces ANY overlap stops the cascade. ALL polities
   whose period overlaps the floruit window are emitted from that location.
2. Phase 2 URL (only if Phase 1 fails): country_of_citizenship → deathplace
   → birthplace. Same overlap-emit logic.

**Joining notes:** any aggregation must use `COUNT(DISTINCT wikidata_id)` for
people-counts; `COUNT(*)` counts (individual, polity) pairs. To get the
"primary" polity for a person, use `arg_max(polity_name, overlap_years)
GROUP BY wikidata_id`.

### `individuals_cliopatria_potential` (9,721,925 rows)

Per-individual flags marking which location signals are *candidates* for
Cliopatria polity matching (the input universe to `individuals_cliopatria`,
before overlap resolution). One row per `wikidata_id` (primary key).

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | VARCHAR | Individual Wikidata ID (PK) |
| `floruit_year` | INTEGER | Floruit year used for the candidacy |
| `polygon_deathplace` | BOOLEAN | True if the death place falls inside a polity polygon |
| `polygon_birthplace` | BOOLEAN | True if the birth place falls inside a polity polygon |
| `polygon_country_of_citizenship` | BOOLEAN | True if the country of citizenship falls inside a polity polygon |
| `url_country_of_citizenship` | BOOLEAN | True if the country of citizenship matched via Wikipedia-URL link |
| `url_deathplace` | BOOLEAN | True if the death place matched via Wikipedia-URL link |
| `url_birthplace` | BOOLEAN | True if the birth place matched via Wikipedia-URL link |

---

## Works

### `works` (38,555,710 rows)

Individual-to-work edges across creative roles.

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGINT | Primary key (autoincrement) |
| `individual_id` | VARCHAR | Individual Wikidata ID |
| `individual_name` | VARCHAR | Individual name |
| `work_id` | VARCHAR | Work Wikidata ID |
| `work_name` | VARCHAR | Work name |
| `relationship` | VARCHAR | Role: `author`, `composer`, `creator`, `director`, `editor`, `illustrator`, `performer`, `producer`, `screenwriter` |
| `instance_of` | VARCHAR | Pipe-joined Wikidata P31 class IDs |
| `instance_of_en` | VARCHAR | Pipe-joined English labels (index-aligned with `instance_of`) |
| `inception_date` | VARCHAR | Inception (P571) ISO timestamp |
| `inception_precision` | BIGINT | Precision: 11=day, 10=month, 9=year, 8=decade, 7=century |
| `publication_date` | VARCHAR | Publication date (P577) ISO timestamp |
| `publication_precision` | BIGINT | Precision (same convention) |

Date columns populated by
`scripts/database_integration_scripts_V2/19_add_dates_to_works/` from JSON
produced by `scripts/wikidata_extraction_scripts_v2/19_extract_work_dates.py`.

---

## Reference Tables

### `occupations` (18,230 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Occupation Wikidata ID |
| `name_en` | VARCHAR | Occupation name |
| `meta_occupation` | VARCHAR | Coarse category: `scientist` or `artist` (NULL for the rest) |
| `count` | BIGINT | Number of individuals |
| `description_en` | VARCHAR | Description |
| `level1_main_occ` | VARCHAR | Top ontology tier: `Leadership`, `Culture`, `Discovery/Science`, `Sports/Games`, `Other`, `Missing` |
| `level2_main_occ` | VARCHAR | Mid ontology tier (e.g. `Culture-core`, `Academia`, `Politics`, `Religious`, `Military`, `Nobility`) |
| `level3_main_occ` | VARCHAR | Fine ontology tier (e.g. `politician`, `writer`, `actor`, `painter`, `historian`) |
| `ontology_n_votes` | BIGINT | Number of votes/observations backing the ontology assignment |

### `country_of_citizenship` (4,572 rows)

Citizenship entities (countries, polities, ethnic groups) referenced by `individuals.country_of_citizenship_en`.

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | VARCHAR | Wikidata ID (PK) |
| `name_en` | VARCHAR | Name |
| `count` | BIGINT | Number of individuals |
| `description_en` | VARCHAR | Description |
| `instance_of` | VARCHAR | Wikidata class |
| `en_wikipedia_url` | VARCHAR | Wikipedia URL |
| `lat` | DOUBLE | Latitude |
| `lon` | DOUBLE | Longitude |
| `iso_country_name` | VARCHAR | Mapped modern country |
| `iso_a3_code` | VARCHAR | ISO 3166-1 alpha-3 code |
| `iso_modern_country_origin` | VARCHAR | Resolution method (see below) |
| `instance_qids` | VARCHAR | Semicolon-separated `instance of` (P31) QIDs |
| `instance_labels` | VARCHAR | English labels for `instance_qids` |
| `inception` | VARCHAR | Inception date (P571) |
| `dissolved` | VARCHAR | Dissolution date (P576) |

**`iso_modern_country_origin` values**:

- `reverse_geocode`: coordinates lookup
- `qlever_relation`: P17/P131/P1366 SPARQL chains
- `qlever_replaced_by`: P1366 "replaced by" chain
- `qlever_2hop_relation` / `qlever_3hop_relation`: multi-hop chains
- `description`: found in Wikidata description
- `name`: found in country-of-citizenship name
- `capital_city`: via capital city's country

### `places` (314,724 rows)

All geographic entities referenced as birth/death locations (cities, settlements, regions, states).

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Place Wikidata ID |
| `name_en` | VARCHAR | Place name |
| `lat` | DOUBLE | Latitude |
| `lon` | DOUBLE | Longitude |
| `original_country_name` | VARCHAR | Country from Wikidata |
| `original_country_name_id` | VARCHAR | Country Wikidata ID |
| `en_wikipedia_url_original_country_name` | VARCHAR | Country Wikipedia URL |
| `iso_country_name` | VARCHAR | Mapped modern country |
| `iso_a3_code` | VARCHAR | ISO 3166-1 alpha-3 code |
| `entity_type` | VARCHAR | Wikidata class label (e.g., "village", "city in the United States") |
| `entity_type_ids` | VARCHAR | Semicolon-separated `instance of` (P31) IDs |
| `is_urban_settlement` | BIGINT | 1 if classified as an urban settlement |
| `inception_date` | VARCHAR | Inception (P571) ISO timestamp |
| `inception_precision` | INTEGER | Precision: 11=day, 10=month, 9=year, 8=decade, 7=century, 6=millennium |
| `dissolution_date` | VARCHAR | Dissolution (P576) ISO timestamp |
| `dissolution_precision` | INTEGER | Precision codes as above |

### `writing_languages` (524 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Language Wikidata ID |
| `name` | VARCHAR | Language name |
| `count` | BIGINT | Number of individuals |

### `individual_writing_languages` (234,476 rows)

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | VARCHAR | Individual ID |
| `individual_name` | VARCHAR | Individual name |
| `language_id` | VARCHAR | Language ID |
| `language_name` | VARCHAR | Language name |

---

## External Identifiers

### `identifiers` (59,508,342 rows)

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | VARCHAR | Individual Wikidata ID |
| `individual_name` | VARCHAR | Individual name |
| `property_id` | VARCHAR | Wikidata property (e.g., P214 for VIAF) |
| `identifier_name` | VARCHAR | System name |
| `value` | VARCHAR | Identifier value |
| `url` | VARCHAR | Direct URL to external record |

### `identifier_types` (5,169 rows)

| Column | Type | Description |
|--------|------|-------------|
| `property_id` | VARCHAR | Wikidata property ID |
| `name_en` | VARCHAR | System name |
| `count` | BIGINT | Number of individuals |
| `description` | VARCHAR | Description |
| `issuer_name` | VARCHAR | Issuing organization |
| `issuer_id` | VARCHAR | Issuer Wikidata ID |
| `issuer_instance` | VARCHAR | Issuer type |
| `country_name` | VARCHAR | Country |
| `country_id` | VARCHAR | Country Wikidata ID |
| `inception` | VARCHAR | Year created |
| `database_records` | VARCHAR | Record count |
| `website` | VARCHAR | Official URL |

---

## Wikipedia Coverage

### `wikimedia_links` (15,551,839 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGINT | ID |
| `wikidata_id` | VARCHAR | Individual Wikidata ID |
| `individual_name` | VARCHAR | Individual name |
| `site` | VARCHAR | Wikipedia language code |
| `title` | VARCHAR | Article title |
| `url` | VARCHAR | Full URL |

---

## Cliopatria Tables

### `polities_cliopatria` (1,604 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGINT | Polity ID |
| `name` | VARCHAR | Polity name |
| `type` | VARCHAR | Polity type (`POLITY`, `RELATION`, …) |
| `wikipedia_url` | VARCHAR | Wikipedia URL |
| `wikidata_id` | VARCHAR | Wikidata ID |
| `number_individuals` | BIGINT | Matched individuals |

### `polities_periods_cliopatria` (13,755 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGINT | ID |
| `polity_id` | BIGINT | References `polities_cliopatria.id` |
| `polity_name` | VARCHAR | Polity name |
| `from_year` | BIGINT | Start year |
| `to_year` | BIGINT | End year |
| `area` | DOUBLE | Polygon area (km²) |
| `geometry` | VARCHAR | GeoJSON polygon |

### `polities_modern_countries_cliopatria` (1,531 rows)

Wikidata-derived mapping from each Cliopatria polity to the present-day
sovereign states it is associated with. One row per (polity, modern country):
when more than one Wikidata pattern produces the same link, the patterns
are pipe-joined into the `sources` column.

| Column | Type | Description |
|--------|------|-------------|
| `polity_id` | BIGINT | References `polities_cliopatria.id` |
| `polity_name` | VARCHAR | Polity name (denormalized copy of `polities_cliopatria.name` for ergonomic joins) |
| `country_qid` | VARCHAR | Modern country Wikidata QID |
| `country_name` | VARCHAR | English label of the country |
| `iso_a3_code` | VARCHAR | ISO 3166-1 alpha-3 code |
| `continent` | VARCHAR | Continent of the modern country (English label, derived from Wikidata P30 via `modern_countries.json`) |
| `sources` | VARCHAR | Pipe-joined sorted list of Wikidata patterns that produced the link: `P17`, `P36/P17` (capital → country), `P1366/P17` (successor → country), `P131/P17` (admin parent → country) |

Built by `scripts/database_integration_scripts_V2/17_create_polities_modern_countries/` from
`scripts/wikidata_extraction_scripts_v2/17_extract_polity_modern_countries.py`.

---

## Metadata

### `wikidata_properties_definition` (49 rows)

Mapping from Wikidata properties to the table/column where they land.

| Column | Type | Description |
|--------|------|-------------|
| `property_id` | VARCHAR | Wikidata property (e.g., P569) |
| `property_name` | VARCHAR | Property label |
| `description` | VARCHAR | Description |
| `table_name` | VARCHAR | Database table |
| `column_name` | VARCHAR | Column name |
