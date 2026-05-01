# database_consolidation/

Post-build consolidation steps that depend on **derived** data, not raw
Wikidata. Run these after `scripts/database_integration_scripts_V2/build_all.py`
has produced `data/humans_v2.sqlite3`.

These scripts are kept separate from the v2 integration pipeline because
they:

- depend on **Cliopatria** geographic / political data (an external
  dataset under `cliopatria_data/`), not Wikidata, and
- compute **time-aware** properties — i.e. they need a notion of *when*
  an individual was active, not just their static facts.

## Layout

| # | Script | What it produces | Inputs |
|---|---|---|---|
| 01 | `01_individuals_floruit_period.py` | `individuals_floruit_period` (working period per Q5: floruit / birth / death rules with century fallback) | `individuals`, `individuals_floruit` |
| 02 | `02_create_polities_cliopatria.py` | `polities_cliopatria` (polity reference table) | `cliopatria_data/processing/data/cliopatria.db` |
| 03 | `03_copy_polity_periods.py` | `cliopatria_polity_periods` (per-period geometries) | same |
| 04 | `04_individuals_cliopatria.py` | `individuals_cliopatria` (each Q5 → polity, polygon-first / URL-fallback, year-aware) | individuals, nationalities, cities, individuals_floruit_period, polities_cliopatria, cliopatria_polity_periods |

## Conceptual flow

```
floruit_period (01)
       │
       ▼
individuals_location ◄── implicit: birth/death/nationality QIDs from individuals
       │                  + lat/lon from cities + nationalities
       ▼
link_to_cliopatria_polities (04)
       │       (uses polity reference 02 + period geometries 03)
       ▼
individuals_cliopatria
```

Script 04 fuses the "pick the right location for someone given their
floruit period" step with the "match that location to the right
Cliopatria polity at that year" step, because the priority order
(nationality → birthplace → deathplace, polygon → URL) is unified across
both stages.

## Database

These scripts read from and write to `data/humans_v2.sqlite3` (set in
`common.py`'s `DB_PATH`). They never touch the legacy
`humans_clean.sqlite3`.

## Running

```bash
python scripts/database_consolidation/01_individuals_floruit_period.py --full
python scripts/database_consolidation/02_create_polities_cliopatria.py --full
python scripts/database_consolidation/03_copy_polity_periods.py --full
python scripts/database_consolidation/04_individuals_cliopatria.py --full
```

Without `--full` each script runs a tiny synthetic-DB sample.
