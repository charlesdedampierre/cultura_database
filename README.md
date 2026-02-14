# Cultura Database

Database of ~2.8 million cultural figures (scientists, writers & artists) extracted from Wikidata.

**Source:** [Wikidata SPARQL endpoint](https://query.wikidata.org/)

## Summary

| Metric | Count |
|--------|-------|
| Occupations | 3,158 |
| Unique individuals | 2,810,360 |
| Individual-occupation mappings | 4,222,528 |

| Category | Occupations | Individuals |
|----------|-------------|-------------|
| artist | 1,300 | 2,446,609 |
| scientist | 1,858 | 1,776,019 |

## Pipeline

### Step 1: Extract Occupations

```bash
python extraction/individuals/01_extract_occupations.py
```

Output: `data/extracted/individuals/occupations.json`

### Step 2: Extract Individuals per Occupation

```bash
python extraction/individuals/02_extract_individuals.py
```

Output: `data/extracted/individuals/occupation/{Q_ID}.json`

For large occupations (cursor-based pagination, 50k/page):

```bash
python extraction/individuals/02e_extract_actor_ids.py      # 365k actors
python extraction/individuals/02f_extract_remaining_ids.py  # historian, economist, theologian, university teacher
python extraction/individuals/02g_extract_writer_ids.py     # 400k writers
```

### Step 3: Create Database

```bash
python create_database.py
```

Output: `cultura_database.db`

## Database Schema

```sql
CREATE TABLE occupations (
    occupation_id TEXT PRIMARY KEY,
    occupation_name TEXT,
    occupation_category TEXT  -- 'artist' or 'scientist'
);

CREATE TABLE individuals (
    wikidata_id TEXT,
    occupation_id TEXT,
    PRIMARY KEY (wikidata_id, occupation_id)
);

CREATE TABLE occupation_counts (
    occupation_id TEXT PRIMARY KEY,
    occupation_name TEXT,
    occupation_category TEXT,
    individual_count INTEGER
);
```

## Top 10 Occupations

| Occupation | Count |
|------------|-------|
| writer | 400,073 |
| actor | 365,015 |
| university teacher | 316,059 |
| poet | 127,034 |
| singer | 123,885 |
| historian | 120,734 |
| composer | 114,573 |
| film director | 99,507 |
| musician | 97,773 |
| teacher | 92,293 |

## External Identifiers

The database includes external identifiers (VIAF, ISNI, IMDb, etc.) for individuals, with metadata about each identifier property.

### Identifier Metadata

Each identifier property includes:

| Column | Description | Source |
|--------|-------------|--------|
| `property_id` | Wikidata property ID (e.g., P214) | Wikidata |
| `property_name` | Human-readable name | Wikidata |
| `count` | Number of individuals with this identifier | Computed |
| `description` | Property description | Wikidata `schema:description` |
| `issuer_name` | Organization maintaining the identifier | Wikidata `P2378` (issued by) |
| `issuer_id` | Wikidata ID of issuer | Wikidata `P2378` |
| `issuer_instance` | Type of issuer organization | Wikidata `P31` of issuer |
| `country_name` | Country of origin | Wikidata `P17` (country) |
| `country_id` | Wikidata ID of country | Wikidata `P17` |
| `inception` | Year created | Wikidata `P571` (inception) |
| `database_records` | Total items in external database | Wikidata `P4876` (number of records) |
| `website` | Source website URL | Wikidata `P1896` (source website) |

All metadata is extracted directly from Wikidata using SPARQL queries.
