# Annotation Guidelines

## Task

Review the AI predictions and validate their accuracy.

## How to Annotate

For each record:

1. Look at the `ai_prediction` column
2. Decide if the prediction is correct
3. Set `is_correct` to `yes` or `no`
4. If `no` or if the case is ambiguous, explain in `notes`

## Columns

| Column | Description |
|--------|-------------|
| `wikidata_id` | Unique identifier (do not modify) |
| `name_en` | Individual's name (for reference) |
| `input_field` | The input data used for prediction |
| `ai_prediction` | What the AI predicted |
| `is_correct` | Your judgment: `yes` or `no` |
| `notes` | Explain disagreements or edge cases |

## When to Mark "no"

- The AI prediction is clearly wrong
- The prediction is defensible but you would choose differently
- The case is ambiguous and the AI made a questionable choice

## Notes Examples

Good notes:
- "Should be X instead of Y because..."
- "Ambiguous case: could be either X or Y"
- "AI missed the primary occupation"

Bad notes:
- "Wrong" (no explanation)
- Empty for incorrect predictions
