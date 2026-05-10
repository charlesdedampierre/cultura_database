# database_consolidation/

Post-build consolidation steps that depend on **derived** data and on
**Cliopatria** geographic / political reference data, run after the raw
Wikidata extraction has populated `data/humans_clean.duckdb`.

These steps add **time-aware** properties to each individual: when they
were active (floruit period) and which historical polity they belong to
during that period.

## Layout

| # | Script | Output | Inputs |
|---|---|---|---|
| 01 | `01_individuals_floruit_period.py` | `individuals_floruit_period` (active period per individual; per-occupation productive-age window) | `individuals` |
| — | `estimate_dates_from_life_expectancy_py.py` | `temp_files/estimated_dates_from_life_expectancy.csv` (cascade-imputed missing date for individuals with one anchor) | `individuals`, CV |
| 02 | `02_create_polities_cliopatria.py` | `polities_cliopatria` (polity reference table) | Cliopatria source DB |
| 03 | `03_copy_polity_periods.py` | `polities_periods_cliopatria` (per-period polygons) | Cliopatria source DB |
| 04 | `04_individuals_cliopatria_rs/` (Rust) | `individuals_cliopatria` — one polity per matched individual; **two-phase cascade** (polygon then URL fallback in one binary) | `individuals_keys`, `places`, `country_of_citizenship`, `individuals_floruit_period`, `polities_cliopatria`, `polities_periods_cliopatria` |
| 06 | `06_flag_non_human_cliopatria.py` | flag column on `individuals` for non-human polity matches | `individuals_cliopatria` |

Script 04 is the unified linker. Phase 1 attempts polygon containment in
order **deathplace → birthplace → centroid of country-of-citizenship**,
restricted to polity-periods covering the impact year. Phase 2 (URL
fallback, applied only when phase 1 fails) tries
**country-of-citizenship URL → deathplace URL → birthplace URL** against
`polities_cliopatria.wikipedia_url`. Impact year is the midpoint of
`floruit_period_start` and `floruit_period_end` when both are present,
else `floruit_year`.

## Database

Reads from and writes to `data/humans_clean.duckdb`.

## Running

```bash
python scripts/database_consolidation/01_individuals_floruit_period.py --full --insert-db
python scripts/database_consolidation/02_create_polities_cliopatria.py --full
python scripts/database_consolidation/03_copy_polity_periods.py --full
cargo run --release --manifest-path scripts/database_consolidation/04_individuals_cliopatria_rs/Cargo.toml -- --db data/humans_clean.duckdb
python scripts/database_consolidation/06_flag_non_human_cliopatria.py
```
