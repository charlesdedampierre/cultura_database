# To do — life-stage polities

To be done when asked.

## 1. Wrong dates for people born BC (the Romans with an empty late stage)

- Marcus Junius Pennus (Q504782): last work −142, death −162. Gaius Caecilius Metellus Caprarius (Q459853): last work −87, death −103. The last work comes after the death, so the late stage runs backwards and nothing can match.
- Cause: in `notebooks_dates/02_works_periods`, "cap the last work at the death" doesn't work for negative years. This is probably also behind the 32 sampled people whose stages are out of order.
- Fix: correct the cap in 02 for BC years. In `01_life_stage_polities`, add a check that skips and counts any stage that ends before it starts.
