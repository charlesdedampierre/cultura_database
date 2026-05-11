# Cultura Database

**13 million scientists, writers, and artists from Wikidata, linked to historical polities (Cliopatria).**

Distributed as a single **DuckDB** file, optimized for analytical queries from
Python (Polars, pandas, Arrow) with no server to run.

---

## Data

| File | Size | Format |
|---|---|---|
| `humans_clean.duckdb` | ~8.8 GB | DuckDB (v1.5+) |

Download from **OSF**: [https://osf.io/](https://osf.io/) *(link TBD)* and
place the file at `data/humans_clean.duckdb` — the path used by every example
and notebook in this repo.

### Key numbers

| Metric | Value |
|---|---|
| Individuals | 13,003,420 |
| Works | 38,555,710 |
| External identifiers | 59,508,342 |
| Wikimedia links (300+ langs) | 15,551,839 |
| Individual ↔ polity mappings | 5,126,001 |
| Historical polities (Cliopatria) | 1,604 |
| Cities (places) | 314,724 |
| Occupations | 18,230 |
| Countries of citizenship | 4,572 |

### Main tables

| Table | Rows | Description |
|---|---|---|
| `individuals` | 13.0M | Core biographical record (one per Q5) |
| `individuals_floruit_period` | 13.0M | Working period per individual (floruit / birth / death rules with century fallback) |
| `individuals_cliopatria` | 5.1M | Individual → historical polity, year-aware (`floruit_year`) |
| `polities_cliopatria` | 1.6K | Historical polities (name, period, modern-country mapping) |
| `places` | 314K | Cities with coordinates and dates |
| `occupations` | 18K | Occupation reference table |
| `country_of_citizenship` | 4.5K | Country reference (P27 values) |
| `wikimedia_links` | 15.6M | Wikipedia / Wikisource / Wikiquote pages |
| `identifiers` | 59.5M | External database links (VIAF, ORCID, etc.) |
| `works` | 38.6M | Works authored / created by individuals |

Full column-level documentation: [docs/DATABASE_SCHEMA.md](docs/DATABASE_SCHEMA.md).

![Database Schema](docs/schema.png)

---

## Installation

Requires **Python 3.11**.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Quick Start

DuckDB returns query results directly as Polars (`.pl()`), pandas (`.df()`)
or Arrow (`.arrow()`) — no copy needed.

```python
import duckdb

con = duckdb.connect("data/humans_clean.duckdb", read_only=True)

# How many individuals?
n = con.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]
print(f"{n:,} individuals")
```

### Query a polity

```python
ottoman_writers = con.execute("""
    SELECT ic.name_en, ic.floruit_year
    FROM individuals_cliopatria ic
    JOIN individuals i USING (wikidata_id)
    WHERE ic.polity_name = 'Ottoman Empire'
      AND i.occupations_en LIKE '%writer%'
    ORDER BY ic.floruit_year
""").pl()
```

### Active individuals over time (50-year bins)

```python
import polars as pl

df = con.execute("""
    SELECT polity_name, floruit_year
    FROM individuals_cliopatria
    WHERE polity_name IN ('Roman Empire', 'Tang Dynasty', 'Ottoman Empire')
      AND floruit_year IS NOT NULL
""").pl()

by_bin = (
    df.with_columns(((pl.col("floruit_year") // 50) * 50).alias("bin"))
      .group_by(["polity_name", "bin"])
      .agg(pl.len().alias("count"))
      .sort(["polity_name", "bin"])
)
```

A complete walk-through (load → query → plot) lives in
[getting_started.ipynb](getting_started.ipynb).

---

## Usage Recommendations

| Workload | Approach |
|---|---|
| Any query against `humans_clean.duckdb` | **DuckDB**, return as Polars (`.pl()`) |
| In-memory dataframes (millions of rows) | **Polars** |
| Small reference tables | pandas is fine |

---

## Paper

A descriptor of this database is under preparation for *Nature Scientific Data*.
Citation, preprint link and DOI will be added here once available.

---

## Citation

```bibtex
@misc{cultura_database,
  title  = {Cultura Database: 13 million scientists, writers, and artists from Wikidata, linked to historical polities},
  author = {de Dampierre, Charles},
  year   = {2026},
  note   = {Version under preparation for Nature Scientific Data}
}
```

---

## License

Data derived from [Wikidata](https://www.wikidata.org/) under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).

---

## Contact

Charles de Dampierre — [cdedampierre@bunka.ai](mailto:cdedampierre@bunka.ai)
