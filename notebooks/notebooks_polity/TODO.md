# To do — life-stage polities

To be done when asked.

## 1. Wrong dates for people born BC (the Romans with an empty late stage)

- Marcus Junius Pennus (Q504782): last work −142, death −162. Gaius Caecilius Metellus Caprarius (Q459853): last work −87, death −103. The last work comes after the death, so the late stage runs backwards and nothing can match.
- Cause: in `notebooks_dates/02_works_periods`, "cap the last work at the death" doesn't work for negative years. This is probably also behind the 32 sampled people whose stages are out of order.
- Fix: correct the cap in 02 for BC years. In `01_life_stage_polities`, add a check that skips and counts any stage that ends before it starts.

## 2. Wrong stage limits (5,218 of 10,002 individuals, 52%)

- A 1-year or backwards stage, or an early stage of 40+ years. 94% of individuals have estimated work dates: the last work is often capped at the death year, so the active and late stages shrink to that year, while the early stage stretches over the adult life.
- Rule: the early stage ends at the first work; with no first work, at age 30.
- A work period that lasts only one year (first work = last work) counts as a single floruit date, like individuals with only a floruit or with only one dated work (one inception). It is to be treated in `notebooks/notebooks_dates/03_floruit_dates_DRAFT.ipynb`. For the moment, their work dates are estimated as if they had no work at all (early stage ends at 30).
- Fix: apply these rules in `01_life_stage_polities`; stop capping estimated work dates at the death in `notebooks_dates/02_works_periods`; merge any stage shorter than about 5 years into its neighbour.
- To decide: the active and late stages of individuals with no work (proposal: active = age 30 → 60 or death, late = age 60 → death).


## 4. Keep a list of polities per stage, not a single pick

- When the winning field has several values (Kepler's work locations Ulm, Graz, Linz, Prague), each is credited with the whole stage and the single pick is arbitrary (202 individuals with a tie).
- Fix: store every polity found for the winning field, one per value; this is fine as long as all the work locations are present.

Not listed here: issues coming from Cliopatria (labels covering a whole era, coastline leaving coastal cities outside the polygons) or from Wikidata (no location at all).
