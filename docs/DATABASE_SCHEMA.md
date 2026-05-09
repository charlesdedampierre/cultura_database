# Cultura Database Schema

Complete documentation of all tables and columns in `data/humans_clean.sqlite3`.

## Core Tables

### `individuals` (13,002,897 rows)

Main biographical data for all individuals.

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Wikidata identifier (e.g., Q937 for Albert Einstein) |
| `name_en` | TEXT | Full name in English |
| `description_en` | TEXT | Short Wikidata description |
| `birthdate` | TEXT | Date of birth (ISO format, negative years for BCE) |
| `birthdate_precision` | INTEGER | Precision: 11=day, 10=month, 9=year, 8=decade, 7=century |
| `deathdate` | TEXT | Date of death |
| `deathdate_precision` | INTEGER | Precision level |
| `country_of_citizenship_en` | TEXT | Semicolon-separated countries of citizenship |
| `birthcity_en` | TEXT | City of birth |
| `deathcity_en` | TEXT | City of death |
| `occupations_en` | TEXT | Semicolon-separated occupations |
| `wikimedia_links_count` | INTEGER | Number of Wikipedia pages across all languages |
| `gender` | TEXT | Gender |
| `identifiers_count` | INTEGER | Number of external database identifiers |
| `writing_language_name_en` | TEXT | Writing language(s) |
| `number_of_works` | INTEGER | Number of works in `works` table for this individual |
| `floruit_date` | TEXT | Floruit date from Wikidata P1317 (ISO format) |
| `floruit_precision` | INTEGER | Precision level for `floruit_date` |
| `floruit_year` | INTEGER | Floruit year derived from `individuals_floruit_period` |
| `works_period` | TEXT | Span of years the individual was producing works. Single year (e.g. `1946`) when first==last, else `min-max` (e.g. `1892-1964`). Per-work effective year = year of `works.publication_date` if present, else `works.inception_date`. NULL when none of the individual's works has a date. BCE preserves the leading `-` (e.g. `-558`). |

### `individuals_keys` (13,002,897 rows)

Raw Wikidata Q-IDs for cross-references.

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Individual Wikidata ID |
| `birthcity_id` | TEXT | Birth city Wikidata ID |
| `deathcity_id` | TEXT | Death city Wikidata ID |
| `country_of_citizenship_ids` | TEXT | Semicolon-separated country-of-citizenship IDs |
| `occupations_ids` | TEXT | Semicolon-separated occupation IDs |
| `gender_id` | TEXT | Gender Wikidata ID |
| `writing_language_ids` | TEXT | Semicolon-separated language IDs |

### `individuals_floruit_period` (13,002,897 rows)

Per-individual floruit window with the method used to derive it.

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Individual Wikidata ID |
| `name_en` | TEXT | Individual name |
| `birthdate` | TEXT | Birth date (ISO format) |
| `birthdate_precision` | INTEGER | Birth date precision |
| `birth_year` | INTEGER | Birth year |
| `deathdate` | TEXT | Death date |
| `deathdate_precision` | INTEGER | Death date precision |
| `death_year` | INTEGER | Death year |
| `floruit_date` | TEXT | Floruit date (ISO format) |
| `floruit_precision` | INTEGER | Floruit date precision |
| `floruit_year` | INTEGER | Floruit year |
| `floruit_period` | TEXT | Period label (e.g., "1962-1987") |
| `floruit_period_start` | INTEGER | Start year of activity window |
| `floruit_period_end` | INTEGER | End year of activity window |
| `method` | TEXT | Derivation method: `birth`, `birth_century`, `death`, `death_century`, or `floruit` |

### `individuals_cliopatria` (6,128,228 rows)

Individual-to-historical-polity mapping (Cliopatria dataset).

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Individual Wikidata ID |
| `name_en` | TEXT | Individual name |
| `polity_name` | TEXT | Historical polity (e.g., "Ottoman Empire") |
| `polity_id` | TEXT | Polity ID in `polities_cliopatria` |
| `origin` | TEXT | Location source: `deathplace`, `birthplace`, `nationality` |
| `matched_name` | TEXT | City or country-of-citizenship name matched |
| `matched_wikidata_id` | TEXT | Wikidata ID of matched entity |
| `method` | TEXT | `merge_with_polygon` or `merge_with_url` |
| `floruit_year` | INTEGER | Floruit year used for temporal matching |
| `floruit_period_start` | INTEGER | Start of floruit window |
| `floruit_period_end` | INTEGER | End of floruit window |

**Matching priority**:

1. Polygon match (coordinates + floruit window against polity boundaries)
2. URL match (Wikipedia URLs with temporal validation)

### `consolidated_database` (5,700,843 rows)

Pre-joined slim view used by analysis notebooks. One row per individual with floruit + polity + occupation flags.

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Individual Wikidata ID |
| `name_en` | TEXT | Individual name |
| `floruit_year` | INTEGER | Floruit year |
| `polity_id` | TEXT | Cliopatria polity ID |
| `polity_name` | TEXT | Cliopatria polity name |
| `occupations` | TEXT | Semicolon-separated occupations |
| `gender` | TEXT | Gender |
| `references_count` | INTEGER | Aggregate reference/citation count |
| `is_scientist` | INTEGER | 1 if any occupation rolls up to "scientist" |
| `is_artist` | INTEGER | 1 if any occupation rolls up to "artist" |

---

## Works

### `works` (38,554,301 rows)

Individual-to-work edges across creative roles.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key (autoincrement) |
| `individual_id` | TEXT | Individual Wikidata ID |
| `individual_name` | TEXT | Individual name |
| `work_id` | TEXT | Work Wikidata ID |
| `work_name` | TEXT | Work name |
| `relationship` | TEXT | Role: `author`, `composer`, `creator`, `director`, `editor`, `illustrator`, `performer`, `producer`, `screenwriter` |
| `instance_of` | TEXT | Pipe-joined Wikidata P31 class IDs |
| `instance_of_en` | TEXT | Pipe-joined English labels (index-aligned with `instance_of`) |
| `inception_date` | TEXT | Inception (P571) ISO timestamp |
| `inception_precision` | INTEGER | Precision: 11=day, 10=month, 9=year, 8=decade, 7=century |
| `publication_date` | TEXT | Publication date (P577) ISO timestamp |
| `publication_precision` | INTEGER | Precision (same convention) |

Date columns populated by
`scripts/database_integration_scripts_V2/19_add_dates_to_works/` from JSON
produced by `scripts/wikidata_extraction_scripts_v2/19_extract_work_dates.py`.
Coverage: 942,320 distinct works with inception and 14,857,897 distinct works
with publication; 37.1M of 38.5M `works` rows now carry at least one date.

---

## Reference Tables

### `occupations` (18,227 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT | Occupation Wikidata ID |
| `name_en` | TEXT | Occupation name |
| `meta_occupation` | TEXT | Parent category: scientist, writer, or artist |
| `count` | INTEGER | Number of individuals |
| `description_en` | TEXT | Description |

### `country_of_citizenship` (3,544 rows)

Citizenship entities (countries, polities, ethnic groups) referenced by `individuals.country_of_citizenship_en`.

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Wikidata ID (PK) |
| `name_en` | TEXT | Name |
| `count` | INTEGER | Number of individuals |
| `description_en` | TEXT | Description |
| `instance_of` | TEXT | Wikidata class |
| `en_wikipedia_url` | TEXT | Wikipedia URL |
| `lat` | REAL | Latitude |
| `lon` | REAL | Longitude |
| `iso_country_name` | TEXT | Mapped modern country |
| `iso_a3_code` | TEXT | ISO 3166-1 alpha-3 code |
| `iso_modern_country_origin` | TEXT | Resolution method (see below) |

**`iso_modern_country_origin` values**:

- `reverse_geocode`: coordinates lookup
- `qlever_relation`: P17/P131/P1366 SPARQL chains
- `qlever_replaced_by`: P1366 "replaced by" chain
- `qlever_2hop_relation` / `qlever_3hop_relation`: multi-hop chains
- `description`: found in Wikidata description
- `name`: found in country-of-citizenship name
- `capital_city`: via capital city's country

### `places` (314,675 rows)

All geographic entities referenced as birth/death locations (cities, settlements, regions, states).

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT | Place Wikidata ID |
| `name_en` | TEXT | Place name |
| `lat` | REAL | Latitude |
| `lon` | REAL | Longitude |
| `original_country_name` | TEXT | Country from Wikidata |
| `original_country_name_id` | TEXT | Country Wikidata ID |
| `en_wikipedia_url_original_country_name` | TEXT | Country Wikipedia URL |
| `iso_country_name` | TEXT | Mapped modern country |
| `iso_a3_code` | TEXT | ISO 3166-1 alpha-3 code |
| `entity_type` | TEXT | Wikidata class label (e.g., "village", "city in the United States") |
| `entity_type_ids` | TEXT | Semicolon-separated `instance of` (P31) IDs |
| `is_urban_settlement` | INTEGER | 1 if classified as an urban settlement |
| `inception_date` | TEXT | Inception (P571) ISO timestamp. 60,660 places. |
| `inception_precision` | INTEGER | Precision: 11=day, 10=month, 9=year, 8=decade, 7=century, 6=millennium |
| `dissolution_date` | TEXT | Dissolution (P576) ISO timestamp. 12,171 places. |
| `dissolution_precision` | INTEGER | Precision codes as above |

### `writing_languages` (524 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT | Language Wikidata ID |
| `name` | TEXT | Language name |
| `count` | INTEGER | Number of individuals |

### `individual_writing_languages` (234,466 rows)

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Individual ID |
| `individual_name` | TEXT | Individual name |
| `language_id` | TEXT | Language ID |
| `language_name` | TEXT | Language name |

---

## External Identifiers

### `identifiers` (59,503,508 rows)

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Individual Wikidata ID |
| `individual_name` | TEXT | Individual name |
| `property_id` | TEXT | Wikidata property (e.g., P214 for VIAF) |
| `identifier_name` | TEXT | System name |
| `value` | TEXT | Identifier value |
| `url` | TEXT | Direct URL to external record |

### `identifier_types` (5,152 rows)

| Column | Type | Description |
|--------|------|-------------|
| `property_id` | TEXT | Wikidata property ID |
| `name_en` | TEXT | System name |
| `count` | INTEGER | Number of individuals |
| `description` | TEXT | Description |
| `issuer_name` | TEXT | Issuing organization |
| `issuer_id` | TEXT | Issuer Wikidata ID |
| `issuer_instance` | TEXT | Issuer type |
| `country_name` | TEXT | Country |
| `country_id` | TEXT | Country Wikidata ID |
| `inception` | TEXT | Year created |
| `database_records` | TEXT | Record count |
| `website` | TEXT | Official URL |

---

## Wikipedia Coverage

### `wikimedia_links` (15,544,183 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | ID |
| `wikidata_id` | TEXT | Individual Wikidata ID |
| `individual_name` | TEXT | Individual name |
| `site` | TEXT | Wikipedia language code |
| `title` | TEXT | Article title |
| `url` | TEXT | Full URL |

---

## Cliopatria Tables

### `polities_cliopatria` (1,604 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Polity ID |
| `name` | TEXT | Polity name |
| `type` | TEXT | Polity type |
| `wikipedia_url` | TEXT | Wikipedia URL |
| `wikidata_id` | TEXT | Wikidata ID |
| `number_individuals` | INTEGER | Matched individuals |

### `polities_periods_cliopatria` (13,755 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | ID |
| `polity_id` | INTEGER | References `polities_cliopatria.id` |
| `polity_name` | TEXT | Polity name |
| `from_year` | INTEGER | Start year |
| `to_year` | INTEGER | End year |
| `area` | REAL | Polygon area |
| `geometry` | TEXT | GeoJSON polygon |

### `polities_modern_countries_cliopatria` (1,531 rows)

Wikidata-derived mapping from each Cliopatria polity to the present-day
sovereign states it is associated with. One row per (polity, modern country):
when more than one Wikidata pattern produces the same link, the patterns
are pipe-joined into the `sources` column.

| Column | Type | Description |
|--------|------|-------------|
| `polity_id` | INTEGER | References `polities_cliopatria.id` |
| `polity_name` | TEXT | Polity name (denormalized copy of `polities_cliopatria.name` for ergonomic joins) |
| `country_qid` | TEXT | Modern country Wikidata QID |
| `country_name` | TEXT | English label of the country |
| `iso_a3_code` | TEXT | ISO 3166-1 alpha-3 code |
| `continent` | TEXT | Continent of the modern country (English label, derived from Wikidata P30 via `modern_countries.json`) |
| `sources` | TEXT | Pipe-joined sorted list of Wikidata patterns that produced the link: `P17`, `P36/P17` (capital → country), `P1366/P17` (successor → country), `P131/P17` (admin parent → country) |

PK: `(polity_id, country_qid)`. Indexes on `polity_id`, `polity_name`, `country_qid`, `iso_a3_code`, `continent`.

Built by `scripts/database_integration_scripts_V2/17_create_polities_modern_countries/` from
`scripts/wikidata_extraction_scripts_v2/17_extract_polity_modern_countries.py`.

---

## Metadata

### `wikidata_properties_definition` (49 rows)

Mapping from Wikidata properties to the table/column where they land.

| Column | Type | Description |
|--------|------|-------------|
| `property_id` | TEXT | Wikidata property (e.g., P569) |
| `property_name` | TEXT | Property label |
| `description` | TEXT | Description |
| `table_name` | TEXT | Database table |
| `column_name` | TEXT | Column name |
