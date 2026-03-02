# Cultura Database

**The largest structured database of cultural figures ever extracted from Wikidata.**

13 million scientists, writers, and artists with their biographies, occupations, nationalities, external identifiers, and Wikipedia sitelinks across all languages.

## Download

The database is available for download on **OSF**: [https://osf.io/](https://osf.io/) *(update with final link)*

| File | Size | Format |
|------|------|--------|
| `humans_clean.sqlite3` | ~14 GB | SQLite3 |

## Key Figures

| Metric | Value |
|--------|-------|
| Unique individuals | **13,002,897** |
| Occupations covered | **18,227** |
| Nationalities | **3,544** |
| Cities (birth/death) | **314,675** |
| External identifier systems | **2,305** |
| Wikipedia sitelinks | **15.5 million** across 300+ languages |
| External identifiers | **30.1 million** |
| Countries represented | **271** |
| Regions | **34** across **9** macro-regions |
| Writing languages | **524** |
| Time span | Antiquity to present |

## Getting Started

### Requirements

- **Python 3.9+**
- `pip install polars pandas`

### Approach 1: Direct SQL Queries (Recommended)

The simplest way to use the database. SQLite streams results without loading everything into memory, making it efficient even on machines with limited RAM.

```python
import sqlite3

conn = sqlite3.connect("humans_clean.sqlite3")
cursor = conn.cursor()

# Count individuals by gender
cursor.execute("""
    SELECT gender, COUNT(*) as n
    FROM individuals
    GROUP BY gender
    ORDER BY n DESC
""")
for row in cursor.fetchall():
    print(f"{row[0]}: {row[1]:,}")

# Find all French writers born after 1800
cursor.execute("""
    SELECT wikidata_id, name_en, birthdate, occupations_en
    FROM individuals
    WHERE nationalities_en LIKE '%French%'
      AND occupations_en LIKE '%writer%'
      AND birthdate >= '1800'
    ORDER BY birthdate
    LIMIT 20
""")
for row in cursor.fetchall():
    print(row)

# Join individuals with sitelinks to find multilingual coverage
cursor.execute("""
    SELECT i.name_en, COUNT(s.site) as n_languages
    FROM individuals i
    JOIN sitelinks s ON i.wikidata_id = s.wikidata_id
    WHERE i.occupations_en LIKE '%physicist%'
    GROUP BY i.wikidata_id
    ORDER BY n_languages DESC
    LIMIT 10
""")
for row in cursor.fetchall():
    print(f"{row[0]}: {row[1]} Wikipedia pages")

conn.close()
```

### Approach 2: Load Tables with Polars or pandas

For analysis that requires working with full tables in memory, load them into DataFrames. Use **Polars** for large tables (millions of rows) and **pandas** for smaller reference tables.

```python
import sqlite3
import polars as pl
import pandas as pd

conn = sqlite3.connect("humans_clean.sqlite3")

# Large tables (millions of rows) -> use Polars for speed and memory efficiency
individuals = pl.read_database("SELECT * FROM individuals", conn)
sitelinks = pl.read_database("SELECT * FROM sitelinks", conn)

# Small reference tables (hundreds to thousands of rows) -> pandas is fine
occupations = pd.read_sql("SELECT * FROM occupations", conn)
nationalities = pd.read_sql("SELECT * FROM nationalities", conn)
countries = pd.read_sql("SELECT * FROM modern_country", conn)
cities = pd.read_sql("SELECT * FROM cities", conn)

conn.close()

# Example: top 20 occupations
print(occupations.sort_values("count", ascending=False).head(20)[["name_en", "count"]])

# Example: individuals per continent using Polars
by_country = (
    individuals
    .select("wikidata_id", "nationalities_en")
    .filter(pl.col("nationalities_en").is_not_null())
    .with_columns(pl.col("nationalities_en").str.split(";").alias("nat_list"))
    .explode("nat_list")
    .with_columns(pl.col("nat_list").str.strip_chars().alias("nationality"))
    .group_by("nationality")
    .agg(pl.col("wikidata_id").count().alias("n"))
    .sort("n", descending=True)
)
print(by_country.head(20))
```

**When to use which:**

| Table | Rows | Recommended |
|-------|------|-------------|
| `individuals` | 13M | Polars or SQL |
| `sitelinks` | 15.5M | Polars or SQL |
| `identifiers` | 30.1M | SQL only (too large for memory) |
| `individuals_countries` | 6.4M | Polars or SQL |
| `individuals_regions` | 5.3M | Polars or SQL |
| `individuals_impact_date` | 7.7M | Polars or SQL |
| `individuals_cliopatria` | 6.2M | Polars or SQL |
| `individuals_keys` | 13M | Polars or SQL |
| `occupations` | 18K | pandas |
| `nationalities` | 3.5K | pandas |
| `cities` | 314K | pandas or Polars |
| `modern_country` | 271 | pandas |
| `regions` | 276 | pandas |
| `writing_languages` | 524 | pandas |
| `identifier_types` | 2.3K | pandas |
| `polities_cliopatria` | 1.6K | pandas |
| `cliopatria_polity_periods` | 15.7K | pandas |
| `properties_definition` | 19 | pandas |

### Why SQLite3?

- **No server required** -- the database is a single portable file.
- **Native Python support** -- `sqlite3` is part of the standard library, no extra install needed.
- **Efficient for data science** -- SQL queries let you filter and aggregate before loading into memory, which is critical for a 13M-row dataset.
- **Interoperable** -- works with pandas, Polars, R, Stata, and any tool that supports SQL.

## Database Schema

### Core Tables

#### `individuals` -- Main table (13,002,897 rows)

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Wikidata identifier (e.g., Q937 for Albert Einstein) |
| `name_en` | TEXT | Full name in English |
| `description_en` | TEXT | Short Wikidata description |
| `birthdate` | TEXT | Date of birth (ISO format, negative years for BCE) |
| `birthdate_precision` | INTEGER | Precision level (9=year, 10=month, 11=day) |
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

#### `individuals_countries` -- Individual-to-country mapping (6,374,506 rows)

Each individual is mapped to a single modern country based on a priority system: nationality first, then birth city, then death city.

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Individual Wikidata ID (PK) |
| `name_en` | TEXT | Individual name |
| `iso_country_name` | TEXT | Modern country name |
| `iso_a3_code` | TEXT | ISO 3166-1 alpha-3 code |
| `origins` | TEXT | How the country was determined: `nationality`, `deathplace`, or `birthplace` |

#### `individuals_regions` -- Individual-to-region mapping (5,319,041 rows)

Each individual is assigned a historical region and macro-region based on their country (from `individuals_countries`) and their impact date year (from `individuals_impact_date`). The mapping uses the `regions` table which defines time-dependent region boundaries. Individuals without an impact date or whose country has no region mapping are excluded.

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Individual Wikidata ID (PK) |
| `name_en` | TEXT | Individual name |
| `iso_country_name` | TEXT | Modern country name |
| `iso_a3_code` | TEXT | ISO 3166-1 alpha-3 code |
| `origins` | TEXT | How the country was determined: `nationality`, `deathplace`, or `birthplace` |
| `region` | TEXT | Region name (e.g., "Balkans", "Nordic countries"); semicolon-separated if multiple |
| `macro_region` | TEXT | Macro-region (e.g., "Western Europe", "Asia"); semicolon-separated if multiple |
| `impact_year` | INTEGER | The individual's impact year used for region matching |

#### `individuals_impact_date` -- Impact date for temporal analysis (7,749,380 rows)

The impact date represents when an individual was most active. It is computed as birthdate + 35 years (estimated peak of career). If birth + 35 exceeds the death date, the death date is used instead. If only a death date exists, it is used directly.

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Individual Wikidata ID (PK) |
| `name_en` | TEXT | Individual name |
| `impact_date` | TEXT | Computed impact date (ISO format) |
| `impact_date_precision` | INTEGER | Precision level (9=year, 10=month, 11=day) |
| `date_source` | TEXT | Source used: `birthdate` or `deathdate` |
| `precision_name` | TEXT | Human-readable precision: `year`, `month`, or `day` |

#### `individuals_cliopatria` -- Individual-to-historical-polity mapping (6,173,349 rows)

Maps individuals to historical polities from the Cliopatria dataset using a two-phase matching system: first polygon-based geospatial matching (using city coordinates and impact date against polity boundaries), then URL-based fallback matching (using Wikipedia URLs). When multiple polities match, the smallest polygon is selected for specificity.

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Individual Wikidata ID (PK) |
| `name_en` | TEXT | Individual name |
| `polity_name` | TEXT | Historical polity name (e.g., "Ottoman Empire") |
| `polity_id` | INTEGER | Polity ID in polities_cliopatria |
| `origin` | TEXT | Location source: `deathplace`, `birthplace`, or `nationality` |
| `matched_name` | TEXT | The city or nationality name that was matched |
| `matched_wikidata_id` | TEXT | Wikidata ID of the matched entity |
| `method` | TEXT | Matching method: `polygon` or `url` |
| `impact_date` | INTEGER | Impact year used for temporal matching |

**Matching priority order:**

1. Nationality coordinates + impact date (polygon match)
2. Nationality Wikipedia URL + impact date (url match)
3. Birth city coordinates + impact date (polygon match)
4. Birth city country Wikipedia URL + impact date (url match)
5. Death city coordinates + impact date (polygon match)
6. Death city country Wikipedia URL + impact date (url match)
7. Nationality/birth/death Wikipedia URL without year check (url_fallback -- only for individuals without impact year)

#### `individuals_keys` -- Wikidata ID cross-references (13,002,897 rows)

Stores the raw Wikidata Q-IDs for each individual's associated entities, enabling unambiguous lookups (e.g., distinguishing Florence, Italy from Florence, Alabama).

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Individual Wikidata ID (PK) |
| `birthcity_id` | TEXT | Birth city Wikidata ID |
| `deathcity_id` | TEXT | Death city Wikidata ID |
| `nationalities_ids` | TEXT | Semicolon-separated nationality Wikidata IDs |
| `occupations_ids` | TEXT | Semicolon-separated occupation Wikidata IDs |
| `gender_id` | TEXT | Gender Wikidata ID |
| `writing_language_ids` | TEXT | Semicolon-separated writing language Wikidata IDs |

### Reference Tables

#### `occupations` -- Occupation reference (18,227 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT | Occupation Wikidata ID |
| `name_en` | TEXT | Occupation name in English |
| `meta_occupation` | TEXT | Parent occupation category (scientist, writer, or artist) |
| `count` | INTEGER | Number of individuals with this occupation |
| `description_en` | TEXT | Occupation description |

#### `nationalities` -- Nationality reference (3,544 rows)

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Nationality Wikidata ID |
| `name_en` | TEXT | Nationality name |
| `count` | INTEGER | Number of individuals |
| `description_en` | TEXT | Description |
| `instance_of` | TEXT | Wikidata class |
| `en_wikipedia_url` | TEXT | English Wikipedia URL |
| `lat` | REAL | Geographic latitude |
| `lon` | REAL | Geographic longitude |
| `iso_country_name` | TEXT | Mapped modern country name |
| `iso_a3_code` | TEXT | ISO 3166-1 alpha-3 code |
| `iso_modern_country_origin` | TEXT | How the modern country was determined (see below) |

**`iso_modern_country_origin` values:**

- **reverse_geocode**: country found by reverse geocoding the nationality's lat/lon coordinates
- **qlever_relation**: found via QLEVER P17/P131/P1366 chains (country, located in, replaced by properties)
- **qlever_replaced_by**: followed P1366 "replaced by" chain to find a modern successor country
- **qlever_2hop_relation**: found via 2-hop QLEVER relation chain
- **qlever_3hop_relation**: found via 3-hop QLEVER relation chain
- **description**: country name found in the Wikidata description text of the nationality
- **name**: country name found in the nationality's own name (e.g., "Kingdom of Serbia" -> Serbia)
- **capital_city**: found via the capital city's country (P36 -> P17)

#### `cities` -- Birth/death cities (314,675 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT | City Wikidata ID |
| `name_en` | TEXT | City name |
| `lat` | REAL | Geographic latitude |
| `lon` | REAL | Geographic longitude |
| `original_country_name` | TEXT | Country name as extracted from Wikidata |
| `original_country_name_id` | TEXT | Wikidata ID of the original country |
| `en_wikipedia_url_original_country_name` | TEXT | Wikipedia URL of the original country |
| `iso_country_name` | TEXT | Mapped modern country name |
| `iso_a3_code` | TEXT | ISO 3166-1 alpha-3 code |

#### `modern_country` -- Country reference (271 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT | Wikidata ID |
| `name` | TEXT | Country name |
| `continent` | TEXT | Continent |
| `iso_a3_code` | TEXT | ISO 3166-1 alpha-3 code |
| `en_wikipedia_url` | TEXT | English Wikipedia URL |
| `count` | INTEGER | Number of individuals associated with this country |

#### `regions` -- Region definitions with temporal bounds (276 rows)

Maps ISO country codes to regions and macro-regions with time periods. A country can belong to different regions in different eras (e.g., Greece belongs to "Greek World" before 500 CE and "Balkans" after). Negative years represent BCE dates.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-increment ID |
| `macro_region` | TEXT | Macro-region (9 values: Western Europe, Eastern Europe, North America, Asia, Latin America, Middle-East and Africa, Sub-Saharan Africa, Oceania, Ancient Mediterranean) |
| `region` | TEXT | Region (34 values: e.g., Balkans, Nordic countries, North America, Japan, Arabic world) |
| `iso_country_name` | TEXT | Country name |
| `iso_a3` | TEXT | ISO 3166-1 alpha-3 code |
| `start_year` | INTEGER | Start year of validity (negative = BCE) |
| `end_year` | INTEGER | End year of validity (NULL = still valid) |

#### `writing_languages` -- Language reference (524 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT | Language Wikidata ID |
| `name` | TEXT | Language name in English |
| `count` | INTEGER | Number of individuals writing in this language |

#### `individual_writing_languages` -- Individual-language mapping (234,466 rows)

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Individual Wikidata ID |
| `individual_name` | TEXT | Individual name |
| `language_id` | TEXT | Language Wikidata ID |
| `language_name` | TEXT | Language name |

### External Identifiers

#### `identifiers` -- External database links (30,100,312 rows)

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Individual Wikidata ID |
| `individual_name` | TEXT | Individual name |
| `property_id` | TEXT | Wikidata property ID (e.g., P214 for VIAF) |
| `identifier_name` | TEXT | Identifier system name |
| `value` | TEXT | Identifier value |
| `url` | TEXT | Direct URL to the external record |

#### `identifier_types` -- Metadata about external identifier systems (2,305 rows)

| Column | Type | Description |
|--------|------|-------------|
| `property_id` | TEXT | Wikidata property ID |
| `name_en` | TEXT | Identifier system name |
| `count` | INTEGER | Number of individuals with this identifier |
| `description` | TEXT | System description |
| `issuer_name` | TEXT | Issuing organization name |
| `issuer_id` | TEXT | Issuing organization Wikidata ID |
| `issuer_instance` | TEXT | Issuer type |
| `country_name` | TEXT | Country of origin |
| `country_id` | TEXT | Country Wikidata ID |
| `inception` | TEXT | Year the system was created |
| `database_records` | TEXT | Number of records in the external database |
| `website` | TEXT | Official website URL |

#### `sitelinks` -- Wikipedia pages (15,544,183 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-increment ID |
| `wikidata_id` | TEXT | Individual Wikidata ID |
| `individual_name` | TEXT | Individual name |
| `site` | TEXT | Wikipedia language code |
| `title` | TEXT | Article title |
| `url` | TEXT | Full URL |

### Cliopatria Tables

These tables support mapping individuals to historical polities using the [Cliopatria](https://cliopatria.io/) dataset.

#### `polities_cliopatria` -- Historical polities (1,618 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Polity ID |
| `name` | TEXT | Polity name (e.g., "Ottoman Empire", "Kingdom of France") |
| `type` | TEXT | Polity type |
| `wikipedia_url` | TEXT | Wikipedia URL |
| `wikidata_id` | TEXT | Wikidata ID |
| `number_individuals` | INTEGER | Number of individuals matched to this polity |

#### `cliopatria_polity_periods` -- Polity time-space boundaries (15,690 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-increment ID |
| `polity_id` | INTEGER | References polities_cliopatria.id |
| `polity_name` | TEXT | Polity name |
| `from_year` | INTEGER | Start year of this period |
| `to_year` | INTEGER | End year of this period |
| `area` | REAL | Polygon area (used to select most specific match) |
| `geometry` | TEXT | GeoJSON polygon geometry |

### Metadata

#### `properties_definition` -- Wikidata properties used (19 rows)

Documents which Wikidata properties (P-numbers) were used to build the database and which tables/columns they map to.

| Column | Type | Description |
|--------|------|-------------|
| `property_id` | TEXT | Wikidata property ID (e.g., P569) |
| `property_name` | TEXT | Property label (e.g., "date of birth") |
| `description` | TEXT | Property description |
| `table_name` | TEXT | Database table(s) using this property |
| `column_name` | TEXT | Column name(s) in the table |

## Key Design Decisions

### Country Assignment Priority

Each individual is mapped to a single modern country using a three-tier priority:

1. **Nationality** (P27) -- if the individual has a country of citizenship, use the first one that maps to a known modern country
2. **Birth city** (P19) -- if no nationality match, use the country of the birth city
3. **Death city** (P20) -- last resort, use the country of the death city

This priority was chosen because nationality is the most reliable indicator of cultural affiliation. Birth city is preferred over death city as a secondary source because it more directly reflects cultural origin, while death city may reflect later-life migration.

### Nationality-to-Modern-Country Resolution

Many Wikidata nationalities refer to historical entities (e.g., "Soviet", "Ottoman", "Prussian"). These were mapped to modern ISO countries through a multi-method pipeline:

1. QLEVER SPARQL queries following P17 (country), P131 (located in), and P1366 (replaced by) chains
2. Reverse geocoding using nationality coordinates
3. Text matching in descriptions and names
4. Capital city resolution

### Impact Date Computation

The "impact date" estimates when an individual was most active:

- **birthdate + 35 years** (estimated career peak)
- If birth + 35 exceeds death date, use **death date** instead
- If only death date exists, use **death date**
- Handles BCE dates (negative years like -500 for 500 BCE)

This date is used for temporal matching with regions and Cliopatria polities.

### Region Classification

Regions are based on the Cliopatria classification system with temporal boundaries. A country can belong to different regions in different eras:

- Greece: "Greek World" (Ancient Mediterranean) before 500 CE, "Balkans" (Eastern Europe) after
- Italy: "Latin World" (Ancient Mediterranean) before 500 CE, "Italy" (Western Europe) after

9 macro-regions: Western Europe, Eastern Europe, North America, Asia, Latin America, Middle-East and Africa (MENA), Sub-Saharan Africa, Oceania, Ancient Mediterranean.

34 sub-regions covering the full geographic and historical scope.

### Cliopatria Polity Matching

Individuals are matched to historical polities (e.g., Ottoman Empire, Kingdom of France) using a priority-based system. The impact year must fall within the polity's time period for all matches (except the final fallback). Polities are identified by their unique ID (not name) to handle duplicate polity names correctly.

**Priority order (for individuals with an impact year):**

1. **Nationality-location polygon** -- nationality coordinates + impact year checked against polity boundary polygons (smallest polygon selected for specificity)
2. **Nationality URL** -- nationality Wikipedia URL matched against polity Wikipedia URLs, with impact year validated against polity time period
3. **Birth-location polygon** -- birth city coordinates + impact year checked against polity boundary polygons
4. **Birth-location country URL** -- birth city's country Wikipedia URL matched against polity URLs, with impact year validation
5. **Death-location polygon** -- death city coordinates + impact year checked against polity boundary polygons
6. **Death-location country URL** -- death city's country Wikipedia URL matched against polity URLs, with impact year validation

**Fallback (for individuals without an impact year only):**

7. **URL matching without year check** -- Wikipedia URLs of nationalities, then birth cities, then death cities matched against polity URLs. This fallback is only used for individuals who have no impact year at all. Individuals who have an impact year but did not match any polity in steps 1-6 remain unmatched.

## Methodology

### 1. Extraction (Python)

All data is extracted from [Wikidata](https://www.wikidata.org/) using SPARQL queries via the [QLever](https://qlever.cs.uni-freiburg.de/) endpoint, which is significantly faster than the default Wikidata Query Service for bulk extraction.

The extraction pipeline:

1. Extract all sub-occupations of "scientist", "writer", and "artist" from the Wikidata ontology.
2. Extract all individuals who hold at least one of these occupations (~13M).
3. For each individual, extract biographical data (name, birth/death dates, cities, nationalities), Wikipedia sitelinks across all languages, and external identifiers (2,300+ systems).
4. All intermediate data is saved as JSON for reproducibility.

Scripts: [`extraction/`](extraction/)

### 2. Database Integration (Rust)

The raw JSON data is loaded into a SQLite3 database and enhanced through a series of 44 numbered Rust scripts. Rust was chosen for its memory efficiency and speed when processing millions of rows.

The enhancement pipeline:

1. **Scripts 01-16**: Create reference tables (modern countries with ISO codes, cities, nationalities), fix encoding issues, add gender/identifier counts/writing languages, clean and reorder tables.
2. **Script 17**: Compute impact dates for temporal analysis.
3. **Scripts 18-27**: Fix nationalities, add ISO codes to cities, create `individuals_countries`, enrich cities with Wikipedia URLs and modern country mappings.
4. **Scripts 28-29**: Create `regions` table with Cliopatria-based regional classification and assign regions to individuals.
5. **Scripts 30-35**: Create Cliopatria URL-based mappings and rebuild tables on clean database.
6. **Scripts 36-42**: Import Cliopatria polity data, match individuals to historical polities via polygon and URL methods, create `individuals_keys` for Wikidata ID cross-references.
7. **Scripts 43-44**: Create `individuals_regions` table and fix `properties_definition`.

Scripts: [`database_integration/enhance_db/`](database_integration/enhance_db/)

### 3. Iterative Cleaning

The database went through multiple rounds of cleaning and verification to ensure data quality:

- Character encoding normalization (UTF-8)
- Deduplication of nationality and city references
- Mapping historical nationalities to modern countries via multi-method pipeline
- Validation of date formats and precision levels
- Batch processing (50,000 rows) with WAL mode for performance on 13M+ row tables

## Repository Structure

```
cultura_database/
├── README.md
├── requirements.txt
├── getting_started.ipynb              # Tutorial notebook
├── extraction/                        # Python scripts to extract data from Wikidata
│   ├── wikidata_api.py                # Shared Wikidata/QLever API utilities
│   ├── all_humans/                    # Main extraction pipeline (34 numbered scripts)
│   │   ├── 01-11: Core human data     # IDs, names, dates, places, nationalities, etc.
│   │   ├── 12-15: Database building   # Build SQLite/DuckDB from JSON
│   │   ├── 16-27: Reference data      # Occupations, nationalities, cities, properties
│   │   ├── 28-33: Enhancement data    # Writing languages, modern countries, identifiers
│   │   └── 34: Monitoring             # Email notification on completion
│   ├── individuals/                   # Individual extraction utilities
│   └── fix_nationalities/             # Rust tool for nationality fixes
└── database_integration/              # Scripts to build and enhance the SQLite3 database
    ├── enhance_db/                    # Main Rust enhancement pipeline (44 numbered scripts)
    │   └── src/bin/
    │       ├── 01_create_modern_country.rs  ... 16_clean_columns.rs
    │       ├── 17_create_impact_date.rs
    │       ├── 18_fix_nationalities.rs  ... 27_fill_nationality_location_countries.rs
    │       ├── 28_create_regions.rs, 28b, 28c  # Region definitions
    │       ├── 29_add_regions_to_individuals_countries.rs
    │       ├── 30-35: Cliopatria URL mappings and clean DB transfer
    │       ├── 36-42: Polity import, polygon matching, individuals_keys
    │       ├── 43_create_individuals_regions.rs
    │       ├── 44_fix_properties_definition.rs
    │       ├── check_schema.rs        # Schema verification utility
    │       └── repair_db.rs           # Database repair utility
    ├── scripts/                       # Python helper scripts
    │   ├── run_30_create_individuals_regions_cliopatria.py
    │   ├── run_31_rebuild_individuals_countries.py
    │   ├── transfer_db.py
    │   └── recover_db.py
    ├── identifier_tools/              # Identifier enrichment (3 scripts)
    ├── load_sitelinks/                # Sitelinks bulk loader
    └── *.c / *.cpp / Makefile         # Legacy C/C++ scripts
```

## Citation

If you use this database in your research, please cite:

```
@misc{cultura_database,
    title={Cultura Database: A Comprehensive Database of Cultural Figures from Wikidata},
    year={2025},
    note={Available at: https://osf.io/}
}
```

## License

The data is derived from [Wikidata](https://www.wikidata.org/) and is available under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).
