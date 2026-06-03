# Cultura Database

**13 million individuals from Wikidata, linked to historical polities (Cliopatria) and with a floruit period.**

Distributed as a single **DuckDB** file, optimized for analytical queries from
Python (Polars, pandas, Arrow) with no server to run.

---

## Data

| File | Size | Format |
|---|---|---|
| `humans_clean.duckdb` | ~8.8 GB | DuckDB (v1.5+) |

For access, send an email to
[charlesdedampierre@gmail.com](mailto:charlesdedampierre@gmail.com). Place the
file at `data/humans_clean.duckdb` — the path used by every example and
notebook in this repo.

### Key numbers

| Metric | Value |
|---|---|
| Individuals | 13,003,420 |
| Works | 38,555,710 |
| External identifiers | 59,508,342 |
| Wikimedia links (300+ langs) | 15,551,839 |
| Individuals linked to a polity | 5,161,090 |
| Individual ↔ polity mappings (pairs) | 7,830,341 |
| Historical polities (Cliopatria) | 1,604 |
| Cities (places) | 314,724 |
| Occupations | 18,230 |
| Countries of citizenship | 4,572 |

### Main tables

| Table | Rows | Description |
|---|---|---|
| `individuals` | 13.0M | Core biographical record (one per Q5) |
| `individuals_floruit_period` | 13.0M | Working period per individual (floruit / birth / death rules with century fallback) |
| `individuals_cliopatria` | 7.8M | Individual → historical polity, year-aware (`floruit_year`); one row per individual–polity pair (5.1M distinct individuals) |
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

## Citation

> Charles de Dampierre, James S. Bennett, Nicolas Baumard.
> *Cultura Database: a comprehensive database of 13 million individuals linked to a floruit period and verified historical polities from 3500 BC to 2026.*

```bibtex
@misc{cultura_database,
  title  = {Cultura Database: a comprehensive database of 13 million individuals linked to a floruit period and verified historical polities from 3500BC to 2026},
  author = {de Dampierre, Charles and Bennett, James S. and Baumard, Nicolas},
  year   = {2026}
}
```

---

## License

Data derived from [Wikidata](https://www.wikidata.org/) under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).

---

## Contact

Charles de Dampierre — [charlesdedampierre@gmail.com](mailto:charlesdedampierre@gmail.com)
