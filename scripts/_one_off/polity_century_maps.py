"""Per-century world maps: polities colored by log(active individuals).

For each century c in [-500, 1900], we:

1. Count individuals in `individuals_cliopatria` whose floruit window
   [floruit_period_start, floruit_period_end] overlaps [c, c+99],
   grouped by polity_id (handling semicolon-joined ids).
2. Pick the geometry from `polities_periods_cliopatria` whose period midpoint
   is closest to c+50 among periods overlapping the century.
3. Render the polities on a world map, colored by log10(count).

Two figures: all individuals; scientists only (`is_scientist=1`).
Outputs:
  - static small multiples PNG (one panel per century)
  - interactive Plotly HTML with century slider
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
from shapely.geometry import shape
from tqdm import tqdm

ROOT = Path("/Users/charlesdedampierre/Desktop/Rsearch Folder/cultura_database")
DB = ROOT / "data" / "humans_clean.sqlite3"
BASEMAP = ROOT / "data" / "ne_110m_admin_0_countries.geojson"
OUT_DIR = ROOT / "notebooks" / "use_cases" / "polity_century_maps"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CENTURIES = list(range(-500, 2000, 100))  # 25 panels: -500 .. 1900
CMAP = "magma"


# --------------------------------------------------------------------------- #
# Data prep
# --------------------------------------------------------------------------- #
def load_individual_polity_floruit() -> pd.DataFrame:
    """One row per individual: wikidata_id, [polity_ids], start, end, is_scientist."""
    with sqlite3.connect(DB) as conn:
        df = pd.read_sql_query(
            """
            SELECT
                ic.wikidata_id,
                ic.polity_id,
                ic.floruit_period_start AS start,
                ic.floruit_period_end   AS end,
                COALESCE(cd.is_scientist, 0) AS is_scientist
            FROM individuals_cliopatria ic
            LEFT JOIN consolidated_database cd USING (wikidata_id)
            WHERE ic.floruit_period_start IS NOT NULL
              AND ic.floruit_period_end   IS NOT NULL
              AND ic.polity_id IS NOT NULL
              AND ic.polity_id <> ''
            """,
            conn,
        )
    df["polity_ids"] = df["polity_id"].str.split(";")
    return df.drop(columns=["polity_id"])


def counts_per_century(df: pd.DataFrame) -> tuple[dict, dict]:
    """Return ({century: {polity_id: count_all}}, {... scientists}).

    An individual counts toward century c iff their floruit window overlaps
    [c, c+99].  They count toward every polity_id in their semicolon list.
    """
    starts = df["start"].to_numpy()
    ends = df["end"].to_numpy()
    is_sci = df["is_scientist"].to_numpy()
    polity_lists = df["polity_ids"].to_numpy()

    all_counts: dict[int, dict[int, int]] = {c: defaultdict(int) for c in CENTURIES}
    sci_counts: dict[int, dict[int, int]] = {c: defaultdict(int) for c in CENTURIES}

    for c in tqdm(CENTURIES, desc="century counts"):
        c_lo, c_hi = c, c + 99
        mask = (starts <= c_hi) & (ends >= c_lo)
        idx = np.flatnonzero(mask)
        for i in idx:
            sci_flag = is_sci[i]
            for pid_str in polity_lists[i]:
                try:
                    pid = int(pid_str)
                except (TypeError, ValueError):
                    continue
                all_counts[c][pid] += 1
                if sci_flag:
                    sci_counts[c][pid] += 1

    return all_counts, sci_counts


# --------------------------------------------------------------------------- #
# Geometry selection
# --------------------------------------------------------------------------- #
def load_geometries() -> pd.DataFrame:
    with sqlite3.connect(DB) as conn:
        gdf = pd.read_sql_query(
            """
            SELECT polity_id, polity_name, from_year, to_year, geometry
            FROM polities_periods_cliopatria
            """,
            conn,
        )
    gdf["mid"] = (gdf["from_year"] + gdf["to_year"]) / 2.0
    return gdf


def select_geometry_per_century(geom_df: pd.DataFrame) -> dict[int, dict[int, dict]]:
    """{century: {polity_id: {'name','geometry':shapely}}}.

    For each (century, polity), pick the period overlapping the century whose
    midpoint is closest to c+50.
    """
    out: dict[int, dict[int, dict]] = {}
    for c in tqdm(CENTURIES, desc="select geoms"):
        c_lo, c_hi, c_mid = c, c + 99, c + 50
        sub = geom_df[(geom_df["from_year"] <= c_hi) & (geom_df["to_year"] >= c_lo)].copy()
        if sub.empty:
            out[c] = {}
            continue
        sub["dist"] = (sub["mid"] - c_mid).abs()
        sub = sub.sort_values("dist").drop_duplicates("polity_id", keep="first")
        century_map: dict[int, dict] = {}
        for _, row in sub.iterrows():
            try:
                geom = shape(json.loads(row["geometry"]))
            except Exception:
                continue
            century_map[int(row["polity_id"])] = {
                "name": row["polity_name"],
                "geometry": geom,
            }
        out[c] = century_map
    return out


# --------------------------------------------------------------------------- #
# Static rendering
# --------------------------------------------------------------------------- #
def _world_basemap() -> gpd.GeoDataFrame | None:
    if BASEMAP.exists():
        return gpd.read_file(BASEMAP)
    return None


def render_small_multiples(
    counts: dict[int, dict[int, int]],
    geoms: dict[int, dict[int, dict]],
    title: str,
    out_path: Path,
) -> None:
    base = _world_basemap()

    log_max = 1.0
    for c in CENTURIES:
        if counts[c]:
            log_max = max(log_max, np.log10(max(counts[c].values()) + 1))
    norm = Normalize(vmin=0, vmax=log_max)

    n = len(CENTURIES)
    ncols = 5
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(ncols * 4.4, nrows * 2.6))
    axes = axes.flatten()

    for ax, c in zip(axes, CENTURIES):
        if base is not None:
            base.boundary.plot(ax=ax, color="#cccccc", linewidth=0.3)

        century_counts = counts[c]
        century_geoms = geoms.get(c, {})
        if century_counts and century_geoms:
            rows = []
            for pid, cnt in century_counts.items():
                g = century_geoms.get(pid)
                if g is None:
                    continue
                rows.append({"polity_id": pid, "name": g["name"], "count": cnt, "geometry": g["geometry"]})
            if rows:
                gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
                gdf["log_count"] = np.log10(gdf["count"] + 1)
                gdf.plot(
                    ax=ax,
                    column="log_count",
                    cmap=CMAP,
                    norm=norm,
                    edgecolor="white",
                    linewidth=0.2,
                    alpha=0.92,
                )

        ax.set_xlim(-180, 180)
        ax.set_ylim(-60, 85)
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        label = f"{c} BCE" if c < 0 else f"{c} CE"
        ax.set_title(label, fontsize=10, pad=2)

    for ax in axes[len(CENTURIES):]:
        ax.set_visible(False)

    fig.suptitle(title, fontsize=13, y=0.995)

    cbar_ax = fig.add_axes([0.25, 0.03, 0.5, 0.012])
    sm = ScalarMappable(norm=norm, cmap=CMAP)
    sm.set_array([])
    cbar = fig.colorbar(sm, cax=cbar_ax, orientation="horizontal")
    cbar.set_label("log10(active individuals + 1)", fontsize=9)
    cbar.ax.tick_params(labelsize=8)

    fig.tight_layout(rect=[0, 0.05, 1, 0.97])
    fig.savefig(out_path, dpi=170, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out_path}")


# --------------------------------------------------------------------------- #
# Interactive Plotly
# --------------------------------------------------------------------------- #
def render_plotly(
    counts: dict[int, dict[int, int]],
    geoms: dict[int, dict[int, dict]],
    title: str,
    out_path: Path,
) -> None:
    """One choropleth-mapbox-style figure using GeoJSON polygons + slider."""
    log_max = 1.0
    for c in CENTURIES:
        if counts[c]:
            log_max = max(log_max, np.log10(max(counts[c].values()) + 1))

    frames = []
    base_data = None

    for c in CENTURIES:
        century_counts = counts[c]
        century_geoms = geoms.get(c, {})
        feats = []
        ids, names, vals, log_vals = [], [], [], []
        for pid, cnt in century_counts.items():
            g = century_geoms.get(pid)
            if g is None:
                continue
            feats.append({
                "type": "Feature",
                "id": str(pid),
                "properties": {"name": g["name"]},
                "geometry": g["geometry"].__geo_interface__,
            })
            ids.append(str(pid))
            names.append(g["name"])
            vals.append(cnt)
            log_vals.append(float(np.log10(cnt + 1)))

        gj = {"type": "FeatureCollection", "features": feats}
        trace = go.Choropleth(
            geojson=gj,
            locations=ids,
            z=log_vals,
            customdata=np.column_stack([names, vals]) if names else None,
            zmin=0,
            zmax=log_max,
            colorscale="Magma",
            marker_line_color="white",
            marker_line_width=0.4,
            colorbar=dict(
                title="log10(n+1)",
                thickness=12,
                len=0.6,
            ),
            hovertemplate="<b>%{customdata[0]}</b><br>active: %{customdata[1]:,}<extra></extra>",
        )
        if base_data is None:
            base_data = [trace]
        label = f"{c} BCE" if c < 0 else f"{c} CE"
        frames.append(go.Frame(data=[trace], name=str(c), layout=go.Layout(title_text=f"{title} — {label}")))

    fig = go.Figure(data=base_data, frames=frames)
    fig.update_geos(
        showcountries=True,
        countrycolor="#dddddd",
        showcoastlines=True,
        coastlinecolor="#bbbbbb",
        projection_type="natural earth",
        showland=True,
        landcolor="#fafafa",
    )
    fig.update_layout(
        title=f"{title} — {CENTURIES[0]} CE",
        margin=dict(l=10, r=10, t=60, b=10),
        sliders=[{
            "active": 0,
            "currentvalue": {"prefix": "Century: "},
            "pad": {"b": 10, "t": 50},
            "steps": [
                {
                    "method": "animate",
                    "label": (f"{c} BCE" if c < 0 else f"{c} CE"),
                    "args": [[str(c)], {"mode": "immediate", "frame": {"duration": 0, "redraw": True}, "transition": {"duration": 0}}],
                }
                for c in CENTURIES
            ],
        }],
    )
    fig.write_html(out_path, include_plotlyjs="cdn")
    print(f"Saved {out_path}")


# --------------------------------------------------------------------------- #
# Entry
# --------------------------------------------------------------------------- #
def main() -> None:
    print("[1/4] Loading individuals_cliopatria + scientist flag…")
    df = load_individual_polity_floruit()
    print(f"      {len(df):,} individual×polity rows")

    print("[2/4] Computing per-century counts…")
    all_counts, sci_counts = counts_per_century(df)

    print("[3/4] Loading + selecting polity geometries per century…")
    geoms = select_geometry_per_century(load_geometries())

    print("[4/4] Rendering figures…")
    render_small_multiples(
        all_counts, geoms,
        title="Active individuals per polity, per century  (log scale)",
        out_path=OUT_DIR / "active_individuals_per_polity_per_century.png",
    )
    render_small_multiples(
        sci_counts, geoms,
        title="Active scientists per polity, per century  (log scale)",
        out_path=OUT_DIR / "active_scientists_per_polity_per_century.png",
    )
    render_plotly(
        all_counts, geoms,
        title="Active individuals per polity",
        out_path=OUT_DIR / "active_individuals_per_polity_per_century.html",
    )
    render_plotly(
        sci_counts, geoms,
        title="Active scientists per polity",
        out_path=OUT_DIR / "active_scientists_per_polity_per_century.html",
    )


if __name__ == "__main__":
    main()
