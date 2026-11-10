# Cultura Database: 13 million individuals with birth, death, and activity dates linked to historical polities (3500 BCE-2024)

Cultura gathers the 13,002,840 humans of Wikidata with their birth and death dates (imputed from comparable
cohorts when missing), an estimated active life, their occupations, and the historical polities they lived in
before, during and after their active life, from the [Cliopatria](https://doi.org/10.1038/s41597-025-04516-9)
geospatial dataset and the [Seshat](https://seshat-db.com) Global History Databank.

## The data

The data is available on Zenodo, [doi:10.5281/zenodo.24110595](https://doi.org/10.5281/zenodo.24110595), in two forms:

| File | Content | Documentation |
| --- | --- | --- |
| `cultura_database_V4.csv.zip` | The simplified database: one row per individual, 28 columns (dates and their sources, active life, occupations, Seshat polities of each life stage) | [docs/csv.md](docs/csv.md) |
| `cultura_database_V4.duckdb` | The complete database: every extracted and enriched field, in 13 tables | [docs/database.md](docs/database.md) |

Place the files in `data/exports/` (CSV) and `data/cultura/` (DuckDB) to run the examples below as written.

## Installation

Requires Python 3.11.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Quick start

Download `cultura_database_V4.csv.zip` (395 MB, 3.5 GB unzipped) from [Zenodo](https://doi.org/10.5281/zenodo.24110595), unzip it, and scan it with [Polars](https://pola.rs):
only the rows a query keeps are loaded, so the 13 million rows never have to fit in memory.

```python
import polars as pl

individuals = pl.scan_csv("data/exports/cultura_database_V4.csv", infer_schema=False)

# Individuals active in Ming China, with their dates and occupations
ming = (
    individuals
    .filter(pl.col("active_life_seshat_polities").str.contains("Great Ming"))
    .select("wikidata_id", "label", "birth_year", "death_year", "active_life_start", "active_life_end", "occupations")
    .collect()
)

# The Seshat polities with the most individuals during their active life
top_polities = (
    individuals
    .select(pl.col("active_life_seshat_polities").str.split(" | ").alias("polity"))
    .explode("polity")
    .drop_nulls()
    .group_by("polity").agg(pl.len().alias("individuals"))
    .sort("individuals", descending=True)
    .head(10)
    .collect()
)
```

Reading the CSV:

- **Years** are text: negative before the common era (`-453`), or a label (`4th BC`, `20th AC`) when the date is
  known only to the century or millennium. `birth_precision` and `death_precision` say which.
- **Sources** say where each value comes from: `birth_source` is `wikidata (P569, date of birth)` or
  `estimated (cohort: …)` with the cohort it was imputed from; `active_life_source` and the three
  `*_polity_source` columns work the same way.
- **Lists** (occupations, polities) are separated by ` | `, polities ordered by the years spent in them.
- **Life stages**: pre-active (birth to the start of the active life), active, and post-active (end of the active
  life to death). `active life ended at death` means there is no post-active stage.

Every column is described in [docs/csv.md](docs/csv.md). A longer walk-through is in [getting_started.ipynb](getting_started.ipynb).

## The complete database (DuckDB)

For fields beyond the CSV (places, positions held, identifiers, works, Wikipedia links), use the DuckDB file. DuckDB needs no server. Open the file read-only and query it with SQL:

```python
import duckdb

con = duckdb.connect("data/cultura/cultura_database_V4.duckdb", read_only=True)

# The polities of each life stage of Marie Curie
con.execute("""
    SELECT entity.label_en AS name,
           list_transform(pre_active_life_polity, match -> match.polity.name) AS pre_active,
           list_transform(active_life_polity, match -> match.polity.name) AS active,
           list_transform(post_active_life_polity, match -> match.polity.name) AS post_active
    FROM individual_enriched
    WHERE entity.qid = 'Q7186'
""").pl()

# The polities with the most individuals active in the sixteenth century
con.execute("""
    SELECT match.polity.name AS polity, count(*) AS individuals
    FROM individual_enriched, unnest(active_life_polity) AS t(match)
    WHERE start_of_active_life.year BETWEEN 1500 AND 1599
    GROUP BY polity
    ORDER BY individuals DESC
    LIMIT 10
""").pl()
```

`individual_enriched` holds the dates, active life, life-stage polities and notability of each individual;
`individual` holds the raw Wikidata fields (places, occupations, positions held, identifiers, works). Both are
keyed by `entity.qid`. Every table is described in [docs/database.md](docs/database.md).

## Repository

| Folder | Content |
| --- | --- |
| `scripts/1-datamodels` | Pydantic models of every table and of the CSV; `write_docs.py` writes `docs/` from them |
| `scripts/2-wikidata_extraction_scripts` | Extraction of the Wikidata records (QLever SPARQL) |
| `scripts/3-raw_to_db` | Building the DuckDB database from the extracted records |
| `scripts/4-database_enrichment` | Dates and active lives (`01_notebooks_dates`), life-stage polities (`02_notebooks_polity`) and enrichment steps 03–11, run in order by `run_all.py` |
| `scripts/6-export` | `export_individuals_csv.py` writes the CSV; `export_researcher_sample.py` a stratified sample |
| `notebooks/notebooks_analysis` | Figures and tables of the paper |
| `notebooks/notebooks_numbers_in_text` | Every number cited in the paper, recomputed from the database |
| `notebooks/notebooks_polity_validation` | Benchmark of the polity assignments against historians' biographies |

## Citation

> Charles de Dampierre, James S. Bennett, Nicolas Baumard.
> *Cultura Database: 13 million individuals with birth, death, and activity dates linked to historical polities (3500 BCE-2024).*

```bibtex
@misc{cultura_database,
  title  = {Cultura Database: 13 million individuals with birth, death, and activity dates linked to historical polities (3500 BCE-2024)},
  author = {de Dampierre, Charles and Bennett, James S. and Baumard, Nicolas},
  year   = {2026},
  doi    = {10.5281/zenodo.24110595},
  url    = {https://doi.org/10.5281/zenodo.24110595}
}
```

## License

The code is released under the [MIT License](LICENSE). The data, derived from [Wikidata](https://www.wikidata.org/),
is released under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).

## Contact

Charles de Dampierre — [charlesdedampierre@gmail.com](mailto:charlesdedampierre@gmail.com)
