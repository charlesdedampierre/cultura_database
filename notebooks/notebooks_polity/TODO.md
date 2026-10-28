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

## 3. Stop matching the country of citizenship by one coordinate point

- Citizenship is placed at the country's centre point, which falls in whatever polity is there ("Germany" gives East Germany, "Czechoslovakia" gives the USSR). 2,294 of 10,002 individuals have a stage decided this way.
- Fix: match citizenship by URL (or Wikidata ID) only, never by coordinates.
- Cost, measured on the 10,002 sample (citizenship by URL kept, other fields unchanged): 483 individuals (4.8%) lose at least one stage, 333 (3.3%) lose every stage. The others fall back to another field.

| Century of birth | Individuals | Lose a stage | Lose everything |
|---|---|---|---|
| 7th c. BC | 1 | 0 | 0 |
| 3rd c. BC | 1 | 0 | 0 |
| 2nd c. BC | 3 | 1 | 1 |
| 1st c. BC | 2 | 1 | 1 |
| 3rd | 1 | 0 | 0 |
| 4th | 4 | 0 | 0 |
| 5th | 9 | 0 | 0 |
| 6th | 8 | 2 | 0 |
| 7th | 10 | 1 | 1 |
| 8th | 13 | 0 | 0 |
| 9th | 9 | 0 | 0 |
| 10th | 11 | 0 | 0 |
| 11th | 18 | 0 | 0 |
| 12th | 29 | 5 (17%) | 5 (17%) |
| 13th | 43 | 4 (9%) | 2 (5%) |
| 14th | 34 | 6 (18%) | 2 (6%) |
| 15th | 89 | 5 (6%) | 4 (4%) |
| 16th | 221 | 9 (4%) | 6 (3%) |
| 17th | 428 | 24 (6%) | 20 (5%) |
| 18th | 930 | 60 (6%) | 57 (6%) |
| 19th | 4,255 | 213 (5%) | 155 (4%) |
| 20th | 3,883 | 152 (4%) | 79 (2%) |
| Total | 10,002 | 483 (4.8%) | 333 (3.3%) |

## 4. Keep a list of polities per stage, not a single pick

- When the winning field has several values (Kepler's work locations Ulm, Graz, Linz, Prague), each is credited with the whole stage and the single pick is arbitrary (202 individuals with a tie).
- Fix: store every polity found for the winning field, one per value; this is fine as long as all the work locations are present.

Not listed here: issues coming from Cliopatria (labels covering a whole era, coastline leaving coastal cities outside the polygons) or from Wikidata (no location at all).
