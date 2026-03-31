# Cultura Database

**13 million scientists, writers, and artists from Wikidata, linked to historical polities.**

## Download

| File | Size | Format |
|------|------|--------|
| `humans_clean.sqlite3` | ~14 GB | SQLite3 |

Download from **OSF**: [https://osf.io/](https://osf.io/) *(link TBD)*

## Quick Start

```python
import sqlite3
import polars as pl

conn = sqlite3.connect("data/humans_clean.sqlite3")

# Load main table with Polars (fast, memory-efficient)
individuals = pl.read_database("SELECT * FROM individuals", conn)
print(f"Total: {len(individuals):,} individuals")

# Example: French writers born after 1800
french_writers = pl.read_database("""
    SELECT wikidata_id, name_en, birthdate, occupations_en
    FROM individuals
    WHERE nationalities_en LIKE '%French%'
      AND occupations_en LIKE '%writer%'
      AND birthdate >= '1800'
    ORDER BY birthdate
    LIMIT 20
""", conn)
print(french_writers)

conn.close()
```

## Key Numbers

| Metric | Value |
|--------|-------|
| Individuals | 13,002,897 |
| Occupations | 18,227 |
| Nationalities | 3,544 |
| Cities | 314,675 |
| Wikipedia sitelinks | 15.5M |
| External identifiers | 30.1M |
| Historical polities (Cliopatria) | 1,618 |

## Main Tables

| Table | Rows | Description |
|-------|------|-------------|
| `individuals` | 13M | Core biographical data |
| `individuals_countries` | 6.4M | Individual → modern country |
| `individuals_regions` | 5.3M | Individual → region/macro-region |
| `individuals_cliopatria` | 6.2M | Individual → historical polity |
| `individuals_impact_date` | 7.7M | Computed impact dates |
| `sitelinks` | 15.5M | Wikipedia pages (300+ languages) |
| `identifiers` | 30.1M | External database links |

## Database Schema

![Database Schema](docs/schema.png)

See [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) for full schema documentation.

## Usage Recommendations

| Table size | Approach |
|------------|----------|
| Large (millions of rows) | Use **Polars** or stream with SQL |
| Small reference tables | **pandas** is fine |
| `identifiers` (30M rows) | SQL streaming only |

## Example Queries

```python
# Scientists in the Ottoman Empire
ottoman_scientists = pl.read_database("""
    SELECT ic.name_en, ic.impact_date, ic.polity_name
    FROM individuals_cliopatria ic
    JOIN individuals i ON ic.wikidata_id = i.wikidata_id
    WHERE ic.polity_name = 'Ottoman Empire'
      AND i.occupations_en LIKE '%scientist%'
    ORDER BY ic.impact_date
""", conn)

# Individuals by macro-region
by_region = pl.read_database("""
    SELECT macro_region, COUNT(*) as n
    FROM individuals_regions
    GROUP BY macro_region
    ORDER BY n DESC
""", conn)

# Most common occupations
top_occupations = pl.read_database("""
    SELECT name_en, count
    FROM occupations
    ORDER BY count DESC
    LIMIT 20
""", conn)
```

## Getting Started

See the [getting_started.ipynb](getting_started.ipynb) notebook for a complete tutorial.

## License

Data derived from [Wikidata](https://www.wikidata.org/) under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).
