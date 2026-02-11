"""Enrich individuals with country code using geopandas point-in-polygon.

Reads birthcity, deathcity, and nationality coordinates from the database.
For each individual, determines country by checking coordinates against
natural earth boundaries. Priority: deathcity > birthcity > nationality.

Updates: individuals.country_code, country_name, country_data_origin
"""

import os
import sqlite3
import sys
import warnings

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
from tqdm import tqdm

tqdm.pandas()
warnings.filterwarnings("ignore", category=FutureWarning)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "loading"))
from utils import get_db_connection

# Load world boundaries (Natural Earth 110m)
WORLD = gpd.read_file(
    "https://naciscdn.org/naturalearth/110m/cultural/ne_110m_admin_0_countries.zip"
)


def point_to_country(lon: float, lat: float) -> tuple[str, str] | None:
    """Map a point (lon, lat) to country (name, iso_a3) via geopandas."""
    try:
        pt = Point(lon, lat)
        result = WORLD[WORLD.geometry.intersects(pt)]
        if len(result) > 0:
            return (result.iloc[0]["NAME"], result.iloc[0]["ISO_A3_EH"])
    except Exception:
        pass
    return None


def get_country_from_locations(conn: sqlite3.Connection, source: str) -> pd.DataFrame:
    """Get country assignments from a location source (birthcity, deathcity, nationality).

    Returns DataFrame with columns: wikidata_id, country_name, country_code, origin
    """
    if source == "birthcity":
        query = """
            SELECT ib.wikidata_id, bc.longitude, bc.latitude
            FROM individual_birthcity ib
            JOIN birthcity bc ON ib.birthcity_wikidata_id = bc.birthcity_wikidata_id
            WHERE bc.longitude IS NOT NULL AND bc.latitude IS NOT NULL
        """
    elif source == "deathcity":
        query = """
            SELECT id.wikidata_id, dc.longitude, dc.latitude
            FROM individual_deathcity id
            JOIN deathcity dc ON id.deathcity_wikidata_id = dc.deathcity_wikidata_id
            WHERE dc.longitude IS NOT NULL AND dc.latitude IS NOT NULL
        """
    elif source == "nationality":
        query = """
            SELECT wikidata_id, longitude, latitude
            FROM individual_nationality
            WHERE longitude IS NOT NULL AND latitude IS NOT NULL
        """
    else:
        return pd.DataFrame()

    df = pd.read_sql_query(query, conn)
    if df.empty:
        return pd.DataFrame()

    # Get unique locations
    df_locs = df[["longitude", "latitude"]].drop_duplicates().reset_index(drop=True)

    print(f"  Mapping {len(df_locs)} unique {source} locations to countries...")
    df_locs["country_info"] = df_locs.progress_apply(
        lambda row: point_to_country(row["longitude"], row["latitude"]),
        axis=1,
    )
    df_locs = df_locs.dropna(subset=["country_info"])
    df_locs["country_name"] = df_locs["country_info"].apply(lambda x: x[0])
    df_locs["country_code"] = df_locs["country_info"].apply(lambda x: x[1])
    df_locs = df_locs.drop("country_info", axis=1)

    # Merge back
    df_merged = pd.merge(df, df_locs, on=["longitude", "latitude"])
    df_merged = df_merged.drop_duplicates("wikidata_id", keep="first")
    df_merged["origin"] = source

    return df_merged[["wikidata_id", "country_name", "country_code", "origin"]]


def main():
    conn = get_db_connection()

    # Get country from each source
    df_deathcity = get_country_from_locations(conn, "deathcity")
    df_birthcity = get_country_from_locations(conn, "birthcity")
    df_nationality = get_country_from_locations(conn, "nationality")

    # Combine with priority: deathcity > birthcity > nationality
    combined = pd.concat([df_deathcity, df_birthcity, df_nationality])

    order = {"deathcity": 0, "birthcity": 1, "nationality": 2}
    combined["sort_key"] = combined["origin"].map(order)
    combined = combined.sort_values("sort_key")
    combined = combined.drop_duplicates("wikidata_id", keep="first")
    combined = combined.drop("sort_key", axis=1)

    print(f"\nAssigned country to {len(combined)} individuals")
    print(f"  By source: {combined['origin'].value_counts().to_dict()}")

    # Update database
    updates = combined[["country_code", "country_name", "origin", "wikidata_id"]].values.tolist()
    conn.executemany(
        """UPDATE individuals
           SET country_code = ?, country_name = ?, country_data_origin = ?
           WHERE wikidata_id = ?""",
        updates,
    )
    conn.commit()

    # Verify
    count = conn.execute(
        "SELECT COUNT(*) FROM individuals WHERE country_code IS NOT NULL"
    ).fetchone()[0]
    print(f"Individuals with country: {count}")

    conn.close()


if __name__ == "__main__":
    main()
