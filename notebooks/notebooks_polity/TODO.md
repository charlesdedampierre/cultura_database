# To do — life-stage polities

To be done when asked.

## 1. Wrong dates for people born BC (the Romans with an empty late stage) — done

- Marcus Junius Pennus (Q504782): last work −142, death −162. Gaius Caecilius Metellus Caprarius (Q459853): last work −87, death −103. The last work comes after the death, so the late stage runs backwards and nothing can match.
- Cause (found): not the BC sign. `notebooks_dates/02_works_periods` capped the estimated last work only at a Wikidata death; these individuals have an estimated death (01_age_at_death), so nothing capped it.
- Done: 02 caps at the database death, Wikidata or estimated. `01_life_stage_polities` drops and counts any stage that ends before it starts.
- Left: re-ingest the new `individual_work_dates.parquet` into `cultura_enriched_v3.2` (`notebooks_dates/ingest_dates.py`), when approved.

## 2. Wrong stage limits (5,218 of 10,002 individuals, 52%) — done

- A 1-year or backwards stage, or an early stage of 40+ years. 94% of individuals have estimated work dates: the last work is often capped at the death year, so the active and late stages shrink to that year, while the early stage stretches over the adult life.
- Rule: with a dated work period, early = birth → first work, active = first work → last work, late = last work → death. Otherwise (no work, estimated work dates, or a one-year work period): early = birth → 30, active = 30 → 60, late = 60 → death.
- A work period that lasts only one year (first work = last work) counts as a single floruit date, like individuals with only a floruit or with only one dated work (one inception). It is treated in `notebooks/notebooks_dates/03_floruit_dates_DRAFT.ipynb` (its "single work year" group: one work or several works dated the same year). 02 keeps that year as it is; `01_life_stage_polities` treats these individuals as having no work (stages at ages 30 and 60).
- An early or late stage shorter than 5 years is merged into the active stage; an active stage shorter than 5 years with no late stage into the early one.

## 4. Keep a list of polities per stage, not a single pick — done

- When the winning field has several values (Kepler's work locations Ulm, Graz, Linz, Prague), each was credited with the whole stage and the single pick was arbitrary (202 individuals with a tie).
- Done: every location of the winning field gives its polity held longest during the stage; the stage keeps the list, longest first.

Not listed here: issues coming from Cliopatria (labels covering a whole era, coastline leaving coastal cities outside the polygons) or from Wikidata (no location at all).
