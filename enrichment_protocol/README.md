# Enrichment Protocol

## Help Us Map 5,000 Years of Human Culture

The Cultura Database contains **13 million individuals** — scientists, writers, artists, politicians — spanning from ancient civilizations to the present day. But raw data is just the beginning.

We're building something bigger: **a living, evolving resource** that researchers worldwide can use to understand how knowledge, art, and ideas have shaped humanity. And we need your help.

## Why Contribute?

Every enrichment you add unlocks new research possibilities:

- **Classify occupations** → Study how professions evolved across centuries
- **Detect languages** → Trace the spread of literary traditions
- **Link to external databases** → Connect individuals to their works, influences, mentors
- **Add geographic precision** → Map cultural production at city or regional level
- **Identify relationships** → Build networks of collaboration and influence

Your contribution — whether a single new field or a comprehensive classification — becomes part of a permanent, open resource used by historians, sociologists, and data scientists around the world.

## Get Published

**All accepted contributions will be featured in a peer-reviewed paper.**

We are preparing a publication that documents the enriched database and its methodology. Every contributor with an accepted enrichment will be listed as a co-author.

**Publication target: December 2026**

This is your opportunity to contribute to a large-scale digital humanities project and receive academic recognition for your work.

## What You Need

- Basic data skills (Python, SQL) — or just AI assistance (Claude, GPT)
- A few hours to process data and validate results
- Willingness to annotate ~200 samples manually (this ensures quality)

No advanced ML expertise required. The protocol is designed so anyone comfortable with data can contribute.

---

## How to Contribute

All contributions must follow this protocol to ensure quality and reproducibility.

### GitHub Workflow

1. **Fork the repository** and create your enrichment folder
2. **Do the enrichment** — Process the data, validate with manual annotations
3. **Open a Pull Request** — Include all required files (see structure below)
4. **Review** — Maintainers will review for accuracy and reproducibility

That's it. No need to open an issue first — just submit your work.

### Large Data Files

If your enrichment data is too large for GitHub (>100MB), upload it to an external service and include the link in your README:

- [OSF](https://osf.io/) (recommended for academic work)
- [Zenodo](https://zenodo.org/)
- [Hugging Face Datasets](https://huggingface.co/datasets)
- Google Drive / Dropbox (with permanent link)

### Data Reconciliation

All enrichment data **must include `wikidata_id`** as the primary key for reconciliation with the main database. This is the unique identifier that links your enrichment to existing records.

```csv
wikidata_id,your_new_field
Q937,value_1
Q5592,value_2
```

Without `wikidata_id`, your contribution cannot be merged.

## Contribution Structure

Each contribution must be submitted as a folder with the following structure:

```
enrichment_protocol/
└── your_enrichment_name/
    ├── README.md           # Documentation (required)
    ├── prompt.txt          # Exact prompt used (required)
    ├── annotations/        # Manual annotations (required)
    │   ├── sample.csv      # Annotated sample
    │   └── guidelines.md   # Annotation guidelines
    ├── output/             # Generated data
    │   └── enrichment.csv  # Final enrichment data
    └── scripts/            # Code used (optional)
        └── enrich.py
```

## Required Documentation

Your `README.md` must include:

### 1. Field Description

| Item | Description |
|------|-------------|
| **Field name** | Name of the new/modified column |
| **Target table** | Which table this enrichment applies to |
| **Data type** | TEXT, INTEGER, BOOLEAN, etc. |
| **Description** | What this field represents |
| **Rationale** | Why this enrichment is useful |

### 2. Methodology

| Item | Description |
|------|-------------|
| **Model** | Exact model used (e.g., `claude-sonnet-4-20250514`, `gpt-4o-2024-08-06`) |
| **API version** | API version or date of inference |
| **Temperature** | Temperature setting used |
| **Context window** | How much context was provided per request |

### 3. Statistics

| Metric | Value |
|--------|-------|
| Total records processed | Number |
| Records enriched | Number |
| Null/missing values | Number (%) |
| Unique values | Number |
| Value distribution | Top categories with counts |

### 4. Manual Annotation (Mandatory)

| Item | Description |
|------|-------------|
| **Sample size** | Minimum 200 records |
| **Annotator** | Who reviewed (expertise) |
| **Annotation method** | Review AI output, mark `is_correct` (yes/no), add `notes` |

### 5. Accuracy Metrics

| Metric | Value |
|--------|-------|
| **Accuracy** | % correct vs manual annotations |
| **Precision** | Per-class if categorical |
| **Recall** | Per-class if categorical |
| **Edge cases** | Known failure modes |

---

## Example Contribution: Occupation Domain Classification

Below is a complete example of an enrichment that classifies occupations into broader domains.

### Field Description

| Item | Description |
|------|-------------|
| **Field name** | `occupation_domain` |
| **Target table** | `individuals` |
| **Data type** | TEXT |
| **Description** | Broad domain of activity: `arts`, `sciences`, `politics`, `religion`, `military`, `sports`, `business`, `other` |
| **Rationale** | Enables high-level analysis of cultural production by domain across time and regions |

### Methodology

| Item | Description |
|------|-------------|
| **Model** | `claude-sonnet-4-20250514` |
| **API version** | 2025-01-01 |
| **Temperature** | 0 |
| **Context window** | Single occupation string per request |

### Prompt

```
prompt.txt
```

```
You are classifying historical occupations into broad domains.

Given an occupation (or list of occupations separated by semicolons), return the PRIMARY domain from this list:
- arts: painters, writers, poets, musicians, composers, actors, architects, sculptors, photographers, filmmakers
- sciences: scientists, mathematicians, physicians, engineers, inventors, researchers, astronomers, biologists, chemists, physicists
- politics: politicians, diplomats, rulers, monarchs, governors, legislators, activists, revolutionaries
- religion: priests, bishops, monks, theologians, religious leaders, missionaries, saints
- military: soldiers, generals, admirals, military officers, warriors, knights
- sports: athletes, football players, basketball players, tennis players, olympians
- business: merchants, entrepreneurs, businesspeople, bankers, industrialists, traders
- other: all other occupations

Rules:
- Return ONLY the domain word, nothing else
- If multiple occupations span different domains, choose the most prominent one
- If unclear, return "other"

Occupation: {occupation}
Domain:
```

### Statistics

| Metric | Value |
|--------|-------|
| Total records processed | 5,556,247 |
| Records enriched | 5,421,893 (97.6%) |
| Null/missing values | 134,354 (2.4%) |
| Unique values | 8 |

**Value distribution:**

| Domain | Count | Percentage |
|--------|-------|------------|
| arts | 1,847,234 | 34.1% |
| politics | 1,203,456 | 22.2% |
| sciences | 892,345 | 16.5% |
| sports | 567,123 | 10.5% |
| religion | 412,567 | 7.6% |
| business | 234,567 | 4.3% |
| military | 178,234 | 3.3% |
| other | 86,367 | 1.6% |

### Manual Annotation

| Item | Description |
|------|-------------|
| **Sample size** | 500 records |
| **Annotator** | 1 domain expert (historian) |
| **Annotation method** | Review AI predictions, mark correct/incorrect, add notes |

**Annotation file:** `annotations/sample.csv`

```csv
wikidata_id,name_en,occupations_en,ai_prediction,is_correct,notes
Q937,Albert Einstein,physicist; philosopher,sciences,yes,
Q5592,Michelangelo,painter; sculptor; architect,arts,yes,
Q307,Galileo Galilei,astronomer; physicist; mathematician,sciences,yes,
Q1001,Mahatma Gandhi,politician; lawyer; activist,politics,yes,could also be religion due to spiritual leadership
Q5593,Leonardo da Vinci,painter; sculptor; architect; engineer,arts,yes,polymath but primarily known as artist
Q2831,Michael Jordan,basketball player; actor; businessperson,sports,yes,
Q859,Plato,philosopher,sciences,no,should be other or philosophy category
Q8023,Nelson Mandela,politician; activist; lawyer,politics,yes,
...
```

The `is_correct` column indicates whether the AI prediction is accurate. The `notes` column explains edge cases or disagreements.

### Accuracy Metrics

| Metric | Value |
|--------|-------|
| **Overall accuracy** | 94.2% |
| **Macro F1-score** | 0.91 |

**Per-class metrics:**

| Domain | Precision | Recall | F1 |
|--------|-----------|--------|-----|
| arts | 0.96 | 0.95 | 0.95 |
| sciences | 0.94 | 0.93 | 0.93 |
| politics | 0.93 | 0.94 | 0.93 |
| religion | 0.95 | 0.92 | 0.93 |
| sports | 0.98 | 0.97 | 0.97 |
| military | 0.89 | 0.86 | 0.87 |
| business | 0.85 | 0.82 | 0.83 |
| other | 0.72 | 0.78 | 0.75 |

**Known edge cases:**

- Polymath figures (e.g., Leonardo da Vinci) may be misclassified depending on occupation order
- "Philosopher" alone defaults to "sciences" but may be "other" in some contexts
- Historical military-politicians (e.g., Napoleon) may vary between "military" and "politics"

---

## Submission Checklist

Before submitting your Pull Request, verify:

- [ ] README.md with all required sections
- [ ] Exact prompt in `prompt.txt`
- [ ] Manual annotations (minimum 200 samples) in `annotations/`
- [ ] Annotation guidelines documented
- [ ] Accuracy ≥ 85% on manual annotations
- [ ] Statistics computed on full dataset
- [ ] Output CSV includes `wikidata_id` column for reconciliation
- [ ] All `wikidata_id` values are valid (format: Q followed by numbers)

## Ideas for Enrichments

Looking for inspiration? Here are fields the community could add:

| Enrichment | Description | Difficulty |
|------------|-------------|------------|
| **Nobel laureates flag** | Boolean for Nobel Prize winners | Easy |
| **Primary language** | Main language of written works | Medium |
| **Education level** | University, self-taught, apprenticeship | Medium |
| **Migration flag** | Did they work outside their birth country? | Medium |
| **Collaboration network** | Links between co-authors, mentors, students | Hard |
| **Cause of death category** | Natural, accident, conflict, execution | Hard |
| **Religious affiliation** | Based on occupation and description | Hard |

Pick one and submit a Pull Request, or propose your own enrichment.

---

## Questions?

Open a GitHub issue to:

- Propose a new enrichment
- Ask questions about the protocol
- Report problems with existing enrichments
- Suggest improvements to the database

**Every contribution matters.** Join us in building the most comprehensive database of human cultural history.
