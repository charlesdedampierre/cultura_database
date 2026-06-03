# Classification Rules: Floruit & Polity Assignment

Hierarchical ordering of rules used to classify individuals in `humans_clean.duckdb`.

---

## 1. Floruit Association

**Source:** `scripts/database_consolidation/01_individuals_floruit_period.py`
(priorities defined L9–54, candidates computed L496–752, winner selected at L756–762 — **lowest priority value wins**).

The script collects every available signal, tags each with a numeric priority, then keeps the single lowest number.

### Tier A — year-precise signals (priority 100–166)

| # | Rule | Priority |
|---|---|---|
| 1 | Floruit property (Wikidata P1317, year-precise) | **100** |
| 2 | Floruit from Wikidata description ("fl 1645", "active 1633") | 110 |
| 3 | Floruit from Wikipedia (span, e.g. "1846–1900") | 115 |
| 4 | Floruit from Wikipedia (single year) | 118 |
| 5 | Works span > 1 year (`first_work_year` → `last_work_year`) | 120 |
| 6 | Works single year (expanded to productive window) | 125 |
| 7 | Birth + death (Wikidata properties P569/P570) | 130 |
| 8 | Birth + death (Wikidata description) | 140 |
| 9 | Birth + death (Cross-Verified DB) | 150 |
| 10 | Birth + death (Wikipedia) | 155 |
| 11 | Birth-only, Wikidata property | 160 |
| 12 | Birth-only, description | 162 |
| 13 | Birth-only, CV | 164 |
| 14 | Birth-only, Wikipedia | 166 |

### Tier B — coarse signals (decade / century, priority 200–223)

| # | Rule | Priority |
|---|---|---|
| 15 | Floruit decade (P1317) | 200 |
| 16 | Floruit century (P1317) | 210 |
| 17 | Birth + death century | 220 |
| 18 | Birth century only | 222 |
| 19 | Death century only | 223 |

### Tier C — life-expectancy fallback (priority 305–310)

| # | Rule | Priority |
|---|---|---|
| 20 | Year-precise birth + estimated death | 305 |
| 21 | Year-precise death + estimated birth | 306 |
| 22 | Both birth and death estimated | 310 |

### Window anchoring (L344–385)

- **Single floruit date** → productive window varying by occupation category:
  - Culture: 30–62
  - Science / Discovery: 33–62
  - Leadership: 34–67
  - Sports / Games: 21–35
  - Other: 29–55
- **Birth + death pair** → `start = birth + lo`, `end = min(birth + hi, death, current_year)`.
- **Works span** → taken verbatim.
- **Century-only** → full century (or two centuries if birth and death cross one).
- **Minimum span guard**: a floruit window is always a range. If clamping by death or current year would leave fewer than `max(10, (hi-lo)//2)` years, the window is walked back so it spans at least that many years.

### Description-date reclassification (A7 override)

When the upstream parser fills `birthdate_in_description` AND `deathdate_in_description` but the gap is `< lo` (e.g., a bishop tenure "1520–1521" parsed as birth=1520, death=1521), this is **not** a real life span. The two dates are reinterpreted as the bracket of a documented active period:

1. Anchor = `floruit_year_in_description` if set, else midpoint of `(desc_b, desc_d)`.
2. Expand via `expand_around_floruit` using the occupation's productive range.
3. Force the documented `[desc_b, desc_d]` to sit inside the resulting window.
4. Emitted as `method = floruit_description` (priority 110), not `birth_death_description` (priority 140).

### Special cutoffs

- **`under_30`** (L485–490): best birth year > `current_year − 30` **and** no explicit floruit signal → no floruit assigned.
- **`no_data`** (L754): no candidates at all → no floruit assigned.

---

## 2. Polity Association (multi-polity)

**Source:** `scripts/database_consolidation/04_individuals_cliopatria_rs/src/main.rs`.

An individual is associated with **every polity whose period overlaps their
floruit window** at the cascade-winning location. A person whose floruit
spans a regime change (e.g. 1900–1935 in Vienna → Austria-Hungary + First
Austrian Republic + Nazi Germany) gets one `individuals_cliopatria` row per
polity.

Two-phase cascade. **Phase 1 must fail entirely before Phase 2 is tried.**
Inside each phase, the location order is fixed and the cascade stops at the
first location that produces any overlap.

### Floruit window

```
if floruit_period_start and floruit_period_end:
    window = [floruit_period_start, floruit_period_end]
elif floruit_year:
    window = [floruit_year, floruit_year]
else:
    individual is skipped
```

A polity-period qualifies iff `period.from_year ≤ window.end` AND
`period.to_year ≥ window.start` (any year of overlap counts).

### Phase 1 — Polygon (point-in-polygon)

| # | Location | Behavior |
|---|---|---|
| 1 | **Deathplace** | All polities whose polygon contains the deathplace point AND whose period overlaps the floruit window |
| 2 | **Birthplace** | Same, for birthplace point |
| 3 | **Country-of-citizenship** | All polities whose polygon contains the CoC centroid AND overlap the window. Aggregated across all `;`-split CoC entries |

### Phase 2 — Wikipedia URL match (only if Phase 1 returned nothing)

| # | Location | Behavior |
|---|---|---|
| 4 | **Country-of-citizenship URL** | All polity-periods with matching URL whose period overlaps the window, across all CoC entries |
| 5 | **Deathplace URL** | Same, for deathplace |
| 6 | **Birthplace URL** | Same, for birthplace |

### Per-polity dedup

Within a (cascade-step, polity) pair, multiple periods of the same polity
collapse into one row: `overlap_years` is the SUM of years covered across all
such periods.

### What changed from the single-polity version

- **Old**: pick one polity whose period **contains the floruit midpoint**, smallest-bbox tiebreaker → one row per individual.
- **New**: pick **all** polities whose period **overlaps the floruit window**, no bbox tiebreaker → one row per (individual, polity).
- The location cascade order is unchanged.
- `overlap_years` is the new column ranking polities by exposure length — use `arg_max(polity_name, overlap_years)` to recover the "primary" polity per individual.

---

## Mental model

- **Floruit** — trust the most specific signal: explicit floruit property → works → birth + death → birth alone → century → estimated.
- **Polity** — geography first, then text: polygon hit on death → birth → citizenship; if none lands, fall back to URL match on citizenship → death → birth; ties broken by smallest territory.

Note that the location order **flips** between the two polity phases: Phase 1 starts at deathplace, Phase 2 starts at citizenship.
