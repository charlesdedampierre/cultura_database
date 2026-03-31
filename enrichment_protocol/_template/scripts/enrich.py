#!/usr/bin/env python3
"""
Template script for AI-assisted enrichment.
Modify this script for your specific enrichment task.
"""

import sqlite3
import polars as pl
from pathlib import Path
from tqdm import tqdm

# Optional: uncomment for Anthropic API
# import anthropic

# Configuration
DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "humans_clean.sqlite3"
OUTPUT_PATH = Path(__file__).parent.parent / "output" / "enrichment.csv"
PROMPT_PATH = Path(__file__).parent.parent / "prompt.txt"

# Load prompt
with open(PROMPT_PATH) as f:
    PROMPT_TEMPLATE = f.read()


def classify(input_text: str) -> str:
    """
    Classify a single input using the AI model.
    Replace this with your actual API call.
    """
    # Example with Anthropic (uncomment and modify):
    # client = anthropic.Anthropic()
    # message = client.messages.create(
    #     model="claude-sonnet-4-20250514",
    #     max_tokens=50,
    #     temperature=0,
    #     messages=[{
    #         "role": "user",
    #         "content": PROMPT_TEMPLATE.format(input_variable=input_text)
    #     }]
    # )
    # return message.content[0].text.strip().lower()

    # Placeholder - replace with actual implementation
    return "other"


def main():
    # Connect to database
    conn = sqlite3.connect(str(DB_PATH))
    conn.text_factory = lambda x: x.decode('utf-8', 'ignore')

    # Load data - modify query as needed
    query = """
        SELECT wikidata_id, name_en, occupations_en
        FROM individuals
        WHERE occupations_en IS NOT NULL
        LIMIT 100  -- Remove limit for full run
    """

    df = pl.read_database(query, conn)
    conn.close()

    print(f"Processing {len(df):,} records...")

    # Process each record
    results = []
    for row in tqdm(df.iter_rows(named=True), total=len(df)):
        result = classify(row["occupations_en"])
        results.append({
            "wikidata_id": row["wikidata_id"],
            "name_en": row["name_en"],
            "input_field": row["occupations_en"],
            "enriched_value": result
        })

    # Save results
    output_df = pl.DataFrame(results)
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    output_df.write_csv(OUTPUT_PATH)

    print(f"Saved to {OUTPUT_PATH}")

    # Print statistics
    print("\nStatistics:")
    print(output_df.group_by("enriched_value").len().sort("len", descending=True))


if __name__ == "__main__":
    main()
