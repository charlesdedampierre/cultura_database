# To do — life-stage polities

To be done when asked.

## 1. Wrong dates for people born BC (the Romans with an empty late stage)

- Marcus Junius Pennus (Q504782): last work −142, death −162. Gaius Caecilius Metellus Caprarius (Q459853): last work −87, death −103. The last work comes after the death, so the late stage runs backwards and nothing can match.
- Cause: in `notebooks_dates/02_works_periods`, "cap the last work at the death" doesn't work for negative years. This is probably also behind the 32 sampled people whose stages are out of order.
- Fix: correct the cap in 02 for BC years. In `01_life_stage_polities`, add a check that skips and counts any stage that ends before it starts.

## 2. Wrong stage limits (5,218 of 10,002 individuals, 52%)

- A 1-year or backwards stage, or an early stage of 40+ years. 94% of individuals have estimated work dates: the last work is often capped at the death year, so the active and late stages shrink to that year, while the early stage stretches over the adult life.
- Rule: the early stage ends at age 30 at the latest (early = birth → min(first work, birth + 30)).
- Fix: apply that cap in `01_life_stage_polities`; stop capping estimated work dates at the death in `notebooks_dates/02_works_periods`; merge any stage shorter than about 5 years into its neighbour.
