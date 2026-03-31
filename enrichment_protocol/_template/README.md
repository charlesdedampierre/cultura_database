# [Enrichment Name]

> Copy this template to create your enrichment contribution.
> Rename the folder to your enrichment name (e.g., `occupation_domain/`).

## Field Description

| Item | Description |
|------|-------------|
| **Field name** | `your_field_name` |
| **Target table** | `individuals` / `occupations` / other |
| **Data type** | TEXT / INTEGER / BOOLEAN |
| **Description** | What this field represents |
| **Rationale** | Why this enrichment is useful for research |

## Methodology

| Item | Description |
|------|-------------|
| **Model** | e.g., `claude-sonnet-4-20250514` |
| **API version** | Date or version |
| **Temperature** | 0 recommended for classification |
| **Context window** | What context was provided |

## Prompt

See `prompt.txt` for the exact prompt used.

## Statistics

| Metric | Value |
|--------|-------|
| Total records processed | |
| Records enriched | |
| Null/missing values | |
| Unique values | |

**Value distribution:**

| Value | Count | Percentage |
|-------|-------|------------|
| | | |

## Manual Annotation

| Item | Description |
|------|-------------|
| **Sample size** | Minimum 200 |
| **Annotators** | |
| **Annotation method** | |
| **Inter-annotator agreement** | |

See `annotations/sample.csv` for annotated data.

## Accuracy Metrics

| Metric | Value |
|--------|-------|
| **Overall accuracy** | |
| **Macro F1-score** | |

**Known edge cases:**
-

## How to Reproduce

```bash
# Install dependencies
pip install anthropic polars

# Run enrichment
python scripts/enrich.py
```
