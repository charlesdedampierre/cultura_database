# Cultura Database Schema

Complete documentation of all tables and columns in the database.

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
| `nationalities_en` | TEXT | Semicolon-separated nationalities |
| `birthcity_en` | TEXT | City of birth |
| `deathcity_en` | TEXT | City of death |
| `occupations_en` | TEXT | Semicolon-separated occupations |
| `sitelinks_count` | INTEGER | Number of Wikipedia pages across all languages |
| `gender` | TEXT | Gender |
| `identifiers_count` | INTEGER | Number of external database identifiers |
| `writing_language_name_en` | TEXT | Writing language(s) |

### `individuals_countries` (6,374,506 rows)

Individual-to-modern-country mapping.

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Individual Wikidata ID |
| `name_en` | TEXT | Individual name |
| `iso_country_name` | TEXT | Modern country name |
| `iso_a3_code` | TEXT | ISO 3166-1 alpha-3 code |
| `origins` | TEXT | Source: `nationality`, `deathplace`, or `birthplace` |

**Priority order**: nationality → death city → birth city.

### `individuals_regions` (5,319,041 rows)

Individual-to-region mapping with temporal context.

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Individual Wikidata ID |
| `name_en` | TEXT | Individual name |
| `iso_country_name` | TEXT | Modern country name |
| `iso_a3_code` | TEXT | ISO 3166-1 alpha-3 code |
| `origins` | TEXT | Source: `nationality`, `deathplace`, or `birthplace` |
| `region` | TEXT | Region name (e.g., "Balkans", "Nordic countries") |
| `macro_region` | TEXT | Macro-region (e.g., "Western Europe", "Asia") |
| `impact_year` | INTEGER | Impact year used for region matching |

**9 macro-regions**: Western Europe, Eastern Europe, North America, Asia, Latin America, Middle-East and Africa, Sub-Saharan Africa, Oceania, Ancient Mediterranean.

**34 sub-regions** covering global and historical scope.

### `individuals_impact_date` (7,749,380 rows)

Computed impact dates for temporal analysis.

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Individual Wikidata ID |
| `name_en` | TEXT | Individual name |
| `impact_date` | TEXT | Computed impact date (ISO format) |
| `impact_date_precision` | INTEGER | Precision level |
| `date_source` | TEXT | Source: `birthdate` or `deathdate` |
| `precision_name` | TEXT | Human-readable: `year`, `month`, or `day` |

**Calculation**:
- Both dates available: `min(birthdate + 35, deathdate)`
- Only birthdate: `birthdate + 35`
- Only deathdate: `deathdate`

### `individuals_cliopatria` (6,173,349 rows)

Individual-to-historical-polity mapping (Cliopatria dataset).

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Individual Wikidata ID |
| `name_en` | TEXT | Individual name |
| `polity_name` | TEXT | Historical polity (e.g., "Ottoman Empire") |
| `polity_id` | INTEGER | Polity ID in `polities_cliopatria` |
| `origin` | TEXT | Location source: `deathplace`, `birthplace`, `nationality` |
| `matched_name` | TEXT | City or nationality name matched |
| `matched_wikidata_id` | TEXT | Wikidata ID of matched entity |
| `method` | TEXT | `polygon` or `url` |
| `impact_date` | INTEGER | Impact year for temporal matching |

**Matching priority**:
1. Polygon match (coordinates + impact year against polity boundaries)
2. URL match (Wikipedia URLs with temporal validation)

### `individuals_keys` (13,002,897 rows)

Raw Wikidata Q-IDs for cross-references.

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Individual Wikidata ID |
| `birthcity_id` | TEXT | Birth city Wikidata ID |
| `deathcity_id` | TEXT | Death city Wikidata ID |
| `nationalities_ids` | TEXT | Semicolon-separated nationality IDs |
| `occupations_ids` | TEXT | Semicolon-separated occupation IDs |
| `gender_id` | TEXT | Gender Wikidata ID |
| `writing_language_ids` | TEXT | Semicolon-separated language IDs |

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

### `nationalities` (3,544 rows)

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Nationality Wikidata ID |
| `name_en` | TEXT | Nationality name |
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
- `name`: found in nationality name
- `capital_city`: via capital city's country

### `cities` (314,675 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT | City Wikidata ID |
| `name_en` | TEXT | City name |
| `lat` | REAL | Latitude |
| `lon` | REAL | Longitude |
| `original_country_name` | TEXT | Country from Wikidata |
| `original_country_name_id` | TEXT | Country Wikidata ID |
| `en_wikipedia_url_original_country_name` | TEXT | Country Wikipedia URL |
| `iso_country_name` | TEXT | Mapped modern country |
| `iso_a3_code` | TEXT | ISO 3166-1 alpha-3 code |

### `modern_country` (271 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT | Wikidata ID |
| `name` | TEXT | Country name |
| `continent` | TEXT | Continent |
| `iso_a3_code` | TEXT | ISO 3166-1 alpha-3 code |
| `en_wikipedia_url` | TEXT | Wikipedia URL |
| `count` | INTEGER | Number of individuals |

### `regions` (276 rows)

Time-dependent region definitions.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | ID |
| `macro_region` | TEXT | Macro-region |
| `region` | TEXT | Region |
| `iso_country_name` | TEXT | Country |
| `iso_a3` | TEXT | ISO code |
| `start_year` | INTEGER | Start year (negative = BCE) |
| `end_year` | INTEGER | End year (NULL = still valid) |

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

### `identifiers` (30,100,312 rows)

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Individual Wikidata ID |
| `individual_name` | TEXT | Individual name |
| `property_id` | TEXT | Wikidata property (e.g., P214 for VIAF) |
| `identifier_name` | TEXT | System name |
| `value` | TEXT | Identifier value |
| `url` | TEXT | Direct URL to external record |

### `identifier_types` (2,305 rows)

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

### `sitelinks` (15,544,183 rows)

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

### `polities_cliopatria` (1,618 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Polity ID |
| `name` | TEXT | Polity name |
| `type` | TEXT | Polity type |
| `wikipedia_url` | TEXT | Wikipedia URL |
| `wikidata_id` | TEXT | Wikidata ID |
| `number_individuals` | INTEGER | Matched individuals |

### `cliopatria_polity_periods` (15,690 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | ID |
| `polity_id` | INTEGER | References `polities_cliopatria.id` |
| `polity_name` | TEXT | Polity name |
| `from_year` | INTEGER | Start year |
| `to_year` | INTEGER | End year |
| `area` | REAL | Polygon area |
| `geometry` | TEXT | GeoJSON polygon |

---

## Metadata

### `properties_definition` (19 rows)

| Column | Type | Description |
|--------|------|-------------|
| `property_id` | TEXT | Wikidata property (e.g., P569) |
| `property_name` | TEXT | Property label |
| `description` | TEXT | Description |
| `table_name` | TEXT | Database table(s) |
| `column_name` | TEXT | Column name(s) |
