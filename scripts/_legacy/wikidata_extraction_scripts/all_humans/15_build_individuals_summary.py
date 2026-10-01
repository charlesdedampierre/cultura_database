"""
Build a summary Parquet for all individuals with:
- name
- century (from birthdate, fallback to deathdate)
- modern country (from nationality country, fallback to deathplace, fallback to birthplace)

Uses Polars vectorized operations for efficiency.
"""

import json
import polars as pl
import time

OUTPUT_DIR = "data/all_humans"


def load_json_as_df(filepath, key_name="id", value_name="value"):
    """Load simple JSON dict as Polars DataFrame."""
    print(f"Loading {filepath}...")
    with open(filepath) as f:
        data = json.load(f)

    records = [(k, v) for k, v in data.items()]
    return pl.DataFrame(records, schema=[key_name, value_name], orient="row")


def main():
    start = time.time()

    # =========================================
    # STEP 1: Load names
    # =========================================
    print("\n=== STEP 1: Loading names ===")
    df_names = load_json_as_df(f"{OUTPUT_DIR}/all_human_names.json", "id", "name")

    # Clean names: remove @en suffix and quotes
    df_names = df_names.with_columns(
        pl.when(pl.col("name").str.ends_with('@en'))
        .then(pl.col("name").str.slice(0, pl.col("name").str.len_chars() - 3))
        .otherwise(pl.col("name"))
        .str.strip_chars('"')
        .alias("name")
    )
    print(f"Names loaded: {len(df_names):,}")

    # =========================================
    # STEP 2: Load birthdates and extract year/century
    # =========================================
    print("\n=== STEP 2: Loading birthdates ===")
    df_birth = load_json_as_df(f"{OUTPUT_DIR}/all_human_birthdates.json", "id", "birthdate")

    # Extract year from ISO date (handles BC dates with leading -)
    df_birth = df_birth.with_columns(
        pl.when(pl.col("birthdate").str.starts_with("-"))
        .then(-pl.col("birthdate").str.slice(1, 4).cast(pl.Int32, strict=False))
        .otherwise(pl.col("birthdate").str.slice(0, 4).cast(pl.Int32, strict=False))
        .alias("birth_year")
    ).drop("birthdate")

    print(f"Birthdates loaded: {len(df_birth):,}")

    # =========================================
    # STEP 3: Load deathdates
    # =========================================
    print("\n=== STEP 3: Loading deathdates ===")
    df_death = load_json_as_df(f"{OUTPUT_DIR}/all_human_deathdates.json", "id", "deathdate")

    df_death = df_death.with_columns(
        pl.when(pl.col("deathdate").str.starts_with("-"))
        .then(-pl.col("deathdate").str.slice(1, 4).cast(pl.Int32, strict=False))
        .otherwise(pl.col("deathdate").str.slice(0, 4).cast(pl.Int32, strict=False))
        .alias("death_year")
    ).drop("deathdate")

    print(f"Deathdates loaded: {len(df_death):,}")

    # =========================================
    # STEP 4: Load nationality -> country mapping
    # =========================================
    print("\n=== STEP 4: Loading nationality country mappings ===")
    with open(f"{OUTPUT_DIR}/nationality_countries.json") as f:
        nat_countries = json.load(f)

    nat_records = []
    for nat_id, info in nat_countries.items():
        if "country_id" in info:
            nat_records.append((nat_id, info["country_id"], info["country_name"]))

    df_nat_countries = pl.DataFrame(
        nat_records,
        schema=["nat_id", "nat_country_id", "nat_country_name"],
        orient="row"
    )
    print(f"Nationality mappings: {len(df_nat_countries):,}")

    # =========================================
    # STEP 5: Load nationalities (individual -> nationality)
    # =========================================
    print("\n=== STEP 5: Loading individual nationalities ===")
    with open(f"{OUTPUT_DIR}/all_human_nationalities.json") as f:
        nationalities = json.load(f)

    # Take first nationality for each individual
    nat_records = []
    for ind_id, nat_list in nationalities.items():
        if nat_list and isinstance(nat_list, list) and len(nat_list) > 0:
            nat_data = nat_list[0]
            if isinstance(nat_data, dict) and 'id' in nat_data:
                nat_records.append((ind_id, nat_data['id']))

    df_ind_nat = pl.DataFrame(nat_records, schema=["id", "nat_id"], orient="row")
    print(f"Individual nationalities: {len(df_ind_nat):,}")

    # Join to get country from nationality
    df_nat_country = df_ind_nat.join(df_nat_countries, on="nat_id", how="left").select([
        "id", "nat_country_id", "nat_country_name"
    ])
    print(f"Individuals with nationality country: {df_nat_country.filter(pl.col('nat_country_id').is_not_null()).height:,}")

    # =========================================
    # STEP 6: Load place locations (place -> country)
    # =========================================
    print("\n=== STEP 6: Loading place locations ===")
    with open(f"{OUTPUT_DIR}/place_locations.json") as f:
        place_locs = json.load(f)

    place_records = []
    for place_id, info in place_locs.items():
        if "country_id" in info:
            place_records.append((place_id, info["country_id"], info["country_name"]))

    df_place_countries = pl.DataFrame(
        place_records,
        schema=["place_id", "place_country_id", "place_country_name"],
        orient="row"
    )
    print(f"Place country mappings: {len(df_place_countries):,}")

    # =========================================
    # STEP 7: Load birthplaces
    # =========================================
    print("\n=== STEP 7: Loading birthplaces ===")
    with open(f"{OUTPUT_DIR}/all_human_birthplaces.json") as f:
        birthplaces = json.load(f)

    bp_records = []
    for ind_id, bp_data in birthplaces.items():
        if isinstance(bp_data, dict) and 'id' in bp_data:
            bp_records.append((ind_id, bp_data['id']))

    df_birthplaces = pl.DataFrame(bp_records, schema=["id", "bp_place_id"], orient="row")
    print(f"Birthplaces: {len(df_birthplaces):,}")

    # Join to get country from birthplace
    df_bp_country = df_birthplaces.join(
        df_place_countries.rename({"place_id": "bp_place_id", "place_country_id": "bp_country_id", "place_country_name": "bp_country_name"}),
        on="bp_place_id", how="left"
    ).select(["id", "bp_country_id", "bp_country_name"])

    # =========================================
    # STEP 8: Load deathplaces
    # =========================================
    print("\n=== STEP 8: Loading deathplaces ===")
    with open(f"{OUTPUT_DIR}/all_human_deathplaces.json") as f:
        deathplaces = json.load(f)

    dp_records = []
    for ind_id, dp_data in deathplaces.items():
        if isinstance(dp_data, dict) and 'id' in dp_data:
            dp_records.append((ind_id, dp_data['id']))

    df_deathplaces = pl.DataFrame(dp_records, schema=["id", "dp_place_id"], orient="row")
    print(f"Deathplaces: {len(df_deathplaces):,}")

    # Join to get country from deathplace
    df_dp_country = df_deathplaces.join(
        df_place_countries.rename({"place_id": "dp_place_id", "place_country_id": "dp_country_id", "place_country_name": "dp_country_name"}),
        on="dp_place_id", how="left"
    ).select(["id", "dp_country_id", "dp_country_name"])

    # =========================================
    # STEP 9: Join everything together
    # =========================================
    print("\n=== STEP 9: Joining all data ===")

    df = df_names
    df = df.join(df_birth, on="id", how="left")
    df = df.join(df_death, on="id", how="left")
    df = df.join(df_nat_country, on="id", how="left")
    df = df.join(df_dp_country, on="id", how="left")
    df = df.join(df_bp_country, on="id", how="left")

    print(f"Joined DataFrame: {df.shape}")

    # =========================================
    # STEP 10: Compute final columns
    # =========================================
    print("\n=== STEP 10: Computing final columns ===")

    # Year: birthdate first, fallback to deathdate
    df = df.with_columns(
        pl.coalesce(["birth_year", "death_year"]).alias("year")
    )

    # Century calculation
    df = df.with_columns(
        pl.when(pl.col("year") > 0)
        .then((pl.col("year") - 1) // 100 + 1)
        .when(pl.col("year") < 0)
        .then((pl.col("year") + 1) // 100 - 1)
        .otherwise(None)
        .cast(pl.Int16)
        .alias("century")
    )

    # Country: nationality > deathplace > birthplace
    df = df.with_columns(
        pl.coalesce(["nat_country_id", "dp_country_id", "bp_country_id"]).alias("country_id"),
        pl.coalesce(["nat_country_name", "dp_country_name", "bp_country_name"]).alias("country_name")
    )

    # Select final columns
    df_final = df.select([
        "id", "name", "year", "century", "country_id", "country_name"
    ])

    print(f"Final DataFrame: {df_final.shape}")

    # =========================================
    # STEP 11: Save results
    # =========================================
    print("\n=== STEP 11: Saving results ===")

    parquet_file = f"{OUTPUT_DIR}/individuals_summary.parquet"
    df_final.write_parquet(parquet_file)
    print(f"Saved to {parquet_file}")

    # =========================================
    # Summary
    # =========================================
    elapsed = time.time() - start
    print(f"\n=== SUMMARY (completed in {elapsed:.1f}s) ===")
    print(f"Total individuals: {len(df_final):,}")
    print(f"With name: {df_final.filter(pl.col('name').is_not_null()).height:,}")
    print(f"With year: {df_final.filter(pl.col('year').is_not_null()).height:,}")
    print(f"With century: {df_final.filter(pl.col('century').is_not_null()).height:,}")
    print(f"With country: {df_final.filter(pl.col('country_id').is_not_null()).height:,}")

    print("\n=== Top 20 Countries ===")
    print(
        df_final.filter(pl.col('country_name').is_not_null())
        .group_by('country_name')
        .agg(pl.len().alias('count'))
        .sort('count', descending=True)
        .head(20)
    )

    print("\n=== Sample data ===")
    print(df_final.head(10))


if __name__ == "__main__":
    main()
