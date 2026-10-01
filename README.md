# Cultura Database

**13 million individuals from Wikidata, with their period of activity and the historical polities (Cliopatria) they lived in.**

A single DuckDB file, queried from Python with no server. For access, email
[charlesdedampierre@gmail.com](mailto:charlesdedampierre@gmail.com) and place
the file at `data/cultura/humans_clean_enriched_v3.duckdb`.

## Installation

Requires Python 3.11.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Quick Start

```python
import duckdb

con = duckdb.connect("data/cultura/humans_clean_enriched_v3.duckdb", read_only=True)

ottoman = con.execute("""
    SELECT individual.entity.label_en AS name, individual_enriched.peak_productivity.label AS active
    FROM individual
    JOIN individual_enriched ON individual_enriched.entity.qid = individual.entity.qid
    WHERE list_contains(list_transform(individual_enriched.polity, match -> match.polity.name), 'Ottoman Empire')
""").pl()
```

A full walk-through is in [getting_started.ipynb](getting_started.ipynb).

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

## License

Data derived from [Wikidata](https://www.wikidata.org/) under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).

## Contact

Charles de Dampierre — [charlesdedampierre@gmail.com](mailto:charlesdedampierre@gmail.com)
