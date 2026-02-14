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
| `occupations` | 18K | pandas |
| `nationalities` | 3.5K | pandas |
| `cities` | 314K | pandas or Polars |
| `modern_country` | 271 | pandas |
| `writing_languages` | 524 | pandas |
| `identifier_types` | 2.3K | pandas |

### Why SQLite3?

- **No server required** — the database is a single portable file.
- **Native Python support** — `sqlite3` is part of the standard library, no extra install needed.
- **Efficient for data science** — SQL queries let you filter and aggregate before loading into memory, which is critical for a 13M-row dataset.
- **Interoperable** — works with pandas, Polars, R, Stata, and any tool that supports SQL.

## Database Schema

### `individuals` — Main table (13,002,897 rows)

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Wikidata identifier (e.g., Q937 for Albert Einstein) |
| `name_en` | TEXT | Full name in English |
| `description_en` | TEXT | Short Wikidata description |
| `birthdate` | TEXT | Date of birth (ISO format) |
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

### `occupations` — Occupation reference (18,227 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT | Occupation Wikidata ID |
| `name_en` | TEXT | Occupation name in English |
| `meta_occupation` | TEXT | Parent occupation category |
| `count` | INTEGER | Number of individuals with this occupation |
| `description_en` | TEXT | Occupation description |

### `nationalities` — Nationality reference (3,544 rows)

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
| `modern_country_name` | TEXT | Mapped modern country |

### `cities` — Birth/death cities (314,675 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT | City Wikidata ID |
| `name_en` | TEXT | City name |
| `lat` | REAL | Geographic latitude |
| `lon` | REAL | Geographic longitude |
| `country_name` | TEXT | Country name |

### `sitelinks` — Wikipedia pages (15,544,183 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-increment ID |
| `wikidata_id` | TEXT | Individual Wikidata ID |
| `individual_name` | TEXT | Individual name |
| `site` | TEXT | Wikipedia language code |
| `title` | TEXT | Article title |
| `url` | TEXT | Full URL |

### `identifiers` — External database links (30,100,312 rows)

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Individual Wikidata ID |
| `individual_name` | TEXT | Individual name |
| `property_id` | TEXT | Wikidata property ID (e.g., P214 for VIAF) |
| `identifier_name` | TEXT | Identifier system name |
| `value` | TEXT | Identifier value |
| `url` | TEXT | Direct URL to the external record |

### `identifier_types` — Metadata about external identifier systems (2,305 rows)

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

### `modern_country` — Country reference (271 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT | Wikidata ID |
| `name` | TEXT | Country name |
| `continent` | TEXT | Continent |
| `iso_a3_code` | TEXT | ISO 3166-1 alpha-3 code |
| `en_wikipedia_url` | TEXT | English Wikipedia URL |
| `count` | INTEGER | Number of individuals |

### `writing_languages` — Language reference (524 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT | Language Wikidata ID |
| `name` | TEXT | Language name in English |
| `count` | INTEGER | Number of individuals writing in this language |

### `individual_writing_languages` — Individual-language mapping (234,466 rows)

| Column | Type | Description |
|--------|------|-------------|
| `wikidata_id` | TEXT | Individual Wikidata ID |
| `individual_name` | TEXT | Individual name |
| `language_id` | TEXT | Language Wikidata ID |
| `language_name` | TEXT | Language name |

### `properties_definition` — Metadata for Wikidata properties used (26 rows)

| Column | Type | Description |
|--------|------|-------------|
| `property_id` | TEXT | Wikidata property ID |
| `property_name` | TEXT | Property label |
| `description` | TEXT | Property description |
| `table_name` | TEXT | Database table using this property |
| `column_name` | TEXT | Column name in the table |

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

The raw JSON data is loaded into a SQLite3 database and enhanced through a series of numbered Rust scripts. Rust was chosen for its memory efficiency and speed when processing millions of rows.

The enhancement pipeline:

1. Create reference tables (modern countries with ISO codes, cities, nationalities).
2. Fix encoding issues across all text fields.
3. Add gender, identifier counts, and writing languages to individuals.
4. Restructure nationality data with geographic coordinates and Wikipedia links.
5. Clean and reorder all tables for usability.

Scripts: [`database_integration/enhance_db/`](database_integration/enhance_db/)

### 3. Iterative Cleaning

The database went through multiple rounds of cleaning and verification to ensure data quality:

- Character encoding normalization (UTF-8)
- Deduplication of nationality and city references
- Mapping historical nationalities to modern countries
- Validation of date formats and precision levels
- Removal of unused columns (instance_of from occupations, wikidata_url from properties)

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
└── database_integration/              # Rust scripts to build and enhance the SQLite3 database
    ├── enhance_db/                    # Main enhancement pipeline (16 numbered scripts)
    │   └── src/bin/
    │       ├── 01_create_modern_country.rs
    │       ├── 02_fix_encoding.rs
    │       ├── ...
    │       ├── 15_reorder_sitelinks.rs
    │       ├── 16_clean_columns.rs
    │       ├── check_schema.rs        # Schema verification utility
    │       └── repair_db.rs           # Database repair utility
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
