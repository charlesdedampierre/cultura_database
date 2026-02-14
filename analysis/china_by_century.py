"""
Analyze individuals from China by century (3000 BC to 1900 AD).
"""

import polars as pl
import matplotlib.pyplot as plt
import numpy as np

DATA_FILE = "data/all_humans/individuals_summary.parquet"
OUTPUT_DIR = "analysis"

# China-related country IDs (dynasties already mapped to these via nationality_countries.json)
CHINA_COUNTRY_IDS = {
    "Q148",   # People's Republic of China
    "Q865",   # Taiwan (dynasties map here via P1366 succession chain)
}


def century_label(c):
    if c < 0:
        return f"{abs(c)}th BC"
    elif c == 1:
        return "1st"
    elif c == 2:
        return "2nd"
    elif c == 3:
        return "3rd"
    else:
        return f"{c}th"


def main():
    print("Loading data...")
    df = pl.read_parquet(DATA_FILE)

    print(f"Total individuals: {len(df):,}")

    # Filter for China
    df_china = df.filter(pl.col("country_id").is_in(CHINA_COUNTRY_IDS))
    print(f"China individuals: {len(df_china):,}")

    # Filter for 3000 BC to 1900 AD (century -30 to 19)
    df_china_filtered = df_china.filter(
        (pl.col("century").is_not_null()) &
        (pl.col("century") >= -30) &
        (pl.col("century") <= 19)
    )
    print(f"China individuals (3000 BC - 1900 AD): {len(df_china_filtered):,}")

    # Count by century
    century_counts = (
        df_china_filtered
        .group_by("century")
        .agg(pl.len().alias("count"))
        .sort("century")
    )

    print("\n=== Century Distribution ===")
    print(century_counts)

    # Convert to pandas for plotting
    df_plot = century_counts.to_pandas()

    # Create figure with 2 subplots
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

    # Color
    bar_color = '#2E86AB'

    # ========== Plot 1: Linear scale ==========
    ax1.bar(df_plot["century"], df_plot["count"], color=bar_color, edgecolor='black', linewidth=0.3)
    ax1.set_xlabel("Century", fontsize=12)
    ax1.set_ylabel("Number of Individuals", fontsize=12)
    ax1.set_title("China: Individuals by Century (Linear Scale)", fontsize=13, fontweight='bold')
    ax1.grid(axis='y', alpha=0.3)
    ax1.set_axisbelow(True)
    ax1.axvline(x=0.5, color='gray', linestyle='--', alpha=0.5)

    # X-ticks
    xticks = list(range(-30, 20, 5))
    ax1.set_xticks(xticks)
    ax1.set_xticklabels([century_label(c) for c in xticks], rotation=45, ha='right')

    # ========== Plot 2: Log scale ==========
    # Replace 0 with small value for log
    counts_log = df_plot["count"].replace(0, 0.5)

    ax2.bar(df_plot["century"], counts_log, color=bar_color, edgecolor='black', linewidth=0.3)
    ax2.set_yscale('log')
    ax2.set_xlabel("Century", fontsize=12)
    ax2.set_ylabel("Number of Individuals (log scale)", fontsize=12)
    ax2.set_title("China: Individuals by Century (Log Scale)", fontsize=13, fontweight='bold')
    ax2.grid(axis='y', alpha=0.3, which='both')
    ax2.set_axisbelow(True)
    ax2.axvline(x=0.5, color='gray', linestyle='--', alpha=0.5)

    # X-ticks
    ax2.set_xticks(xticks)
    ax2.set_xticklabels([century_label(c) for c in xticks], rotation=45, ha='right')

    plt.tight_layout()

    # Save
    output_file = f"{OUTPUT_DIR}/china_by_century.png"
    plt.savefig(output_file, dpi=150)
    print(f"\nSaved plot to {output_file}")

    # Also save data as CSV
    csv_file = f"{OUTPUT_DIR}/china_by_century.csv"
    century_counts.write_csv(csv_file)
    print(f"Saved data to {csv_file}")

    plt.close()


if __name__ == "__main__":
    main()
