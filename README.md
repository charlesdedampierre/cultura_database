# Cultura Database

A database of cultural figures (artists, scientists, writers) born before 1850, sourced from Wikidata and enriched with geographic, temporal, and bibliographic metadata.

## Pipeline Overview

The project follows three phases:

```
Extract (SPARQL -> JSON) -> Load (JSON -> SQLite) -> Enrich (SQLite -> SQLite)
```

### Phase 1: Extraction (`extraction/`)

SPARQL queries against Wikidata, saving results as JSON to `data/extracted/`.

```bash
# Run in order:
python extraction/individuals/01_extract_occupations.py
python extraction/individuals/02_extract_individuals.py
python extraction/individuals/03_extract_individual_info.py
python extraction/individuals/04_extract_sitelinks.py
python extraction/individuals/05_extract_birthcity_details.py
python extraction/individuals/06_extract_deathcity_details.py
python extraction/individuals/07_extract_nationality_coords.py
python extraction/individuals/08_extract_identifiers.py
python extraction/individuals/09_extract_deathyear.py

python extraction/works/01_extract_notable_works.py
python extraction/works/02_extract_authored_works.py
python extraction/works/03_extract_work_instances.py
python extraction/works/04_extract_work_identifiers.py
```

### Phase 2: Loading (`loading/`)

Reads JSON from `data/extracted/` and inserts into SQLite at `data/cultura.db`.

```bash
python loading/01_load_individuals.py
python loading/02_load_occupations.py
python loading/03_load_locations.py
python loading/04_load_sitelinks.py
python loading/05_load_identifiers.py
python loading/06_load_works.py
python loading/07_load_deathyear.py
python loading/08_load_reference_tables.py
```

### Phase 3: Enrichment (`enrichment/`)

Reads from the database, computes derived data, writes back.

```bash
python enrichment/01_enrich_country.py       # Geopandas point-in-polygon -> country
python enrichment/02_enrich_impact_years.py   # birthyear -> impact year range
python enrichment/03_enrich_regions.py        # Country+time+space -> regions
python enrichment/04_enrich_regions_manual.py # Manual corrections from Excel/CSV
python enrichment/05_clean_individuals.py     # Final filters -> individuals_kept
```

## Database Schema

### Core tables

| Table | Description |
|-------|-------------|
| `individuals` | Wikidata ID, name, birthyear, country, impact years |
| `individual_gender` | Gender per individual |
| `occupations` | Occupation types (artist, scientist, writer subtypes) |
| `individual_occupations` | Individual-to-occupation mapping |
| `individuals_kept` | Filtered subset of individuals passing quality checks |

### Location tables

| Table | Description |
|-------|-------------|
| `individual_birthcity` | Birth city per individual |
| `birthcity` | Birth city metadata (country, coordinates) |
| `individual_deathcity` | Death city per individual |
| `deathcity` | Death city metadata (country, coordinates) |
| `individual_nationality` | Nationality with coordinates |

### Works tables

| Table | Description |
|-------|-------------|
| `works` | Work metadata (instance type, creation year) |
| `individual_works` | Individual-to-work mapping (notable_work or creator) |
| `work_identifiers` | External identifiers for works |

### Reference tables

| Table | Description |
|-------|-------------|
| `identifiers` | External identifier types (VIAF, GND, etc.) |
| `individual_identifiers` | Individual-to-identifier mapping |
| `individual_sitelinks` | Wikipedia page URLs per individual |
| `individual_viaf` | VIAF IDs per individual |
| `deathyear` | Death year per individual |
| `regions` | Region codes and names |
| `individual_regions` | Individual-to-region mapping |
| `country_continent` | Country-to-continent mapping |

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Project Structure

```
cultura_database/
├── extraction/              # Phase 1: SPARQL -> JSON
│   ├── wikidata_api.py      # Shared SPARQL wrapper
│   ├── individuals/         # 9 extraction scripts
│   └── works/               # 4 extraction scripts
├── loading/                 # Phase 2: JSON -> SQLite
│   ├── utils.py             # DB connection, helpers
│   └── 01-08 scripts        # One per table group
├── enrichment/              # Phase 3: SQLite -> SQLite
│   └── 01-05 scripts        # Country, impact years, regions, cleanup
├── data/
│   ├── extracted/           # JSON output from extraction
│   └── cultura.db           # The SQLite database
├── scraping/                # Original extraction scripts (reference)
├── archive/                 # Legacy code and Wikipedia data
├── requirements.txt
└── .env
```

## Quick Query Example

```python
import sqlite3
import pandas as pd

conn = sqlite3.connect("data/cultura.db")

# Get all kept individuals with their country
df = pd.read_sql_query("""
    SELECT i.wikidata_id, i.name, i.birthyear, i.country_name
    FROM individuals i
    JOIN individuals_kept k ON i.wikidata_id = k.wikidata_id
    ORDER BY i.birthyear
""", conn)
```

## Data Sources

- [Wikidata](https://www.wikidata.org/) via SPARQL endpoint
- [Natural Earth](https://www.naturalearthdata.com/) for country boundaries (via geopandas)
- Manual corrections from ENS Cultural Index research
