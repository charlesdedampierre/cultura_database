"""Streamlit app: browse Cross-Verified individuals by country of citizenship.

Run with:

    .venv/bin/streamlit run scripts/cv_country_explorer.py

Filters CV rows by tokens found in the raw upstream citizenship string
(`string_citizenship_raw_d`) and shows individuals + their metadata.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import streamlit as st

TOKEN_RE = re.compile(r"'([^']+)'")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "cv_country_explorer.parquet"

DISPLAY_COLS = [
    "name",
    "gender",
    "birth",
    "death",
    "level1_main_occ",
    "level2_main_occ",
    "level3_main_occ",
    "citizenship_1_b",
    "citizenship_2_b",
    "string_citizenship_raw_d",
    "un_region",
    "un_subregion",
    "bigperiod_birth",
    "bigperiod_death",
    "wiki_readers_2015_2018",
    "number_wiki_editions",
    "ranking_visib_5criteria",
    "wikidata_code",
]


@st.cache_data(show_spinner="Loading CV database...")
def load_cv() -> pd.DataFrame:
    df = pd.read_parquet(DATA)
    return df


@st.cache_data
def raw_token_counts(df: pd.DataFrame) -> pd.Series:
    """Explode `string_citizenship_raw_d` into individual tokens and count rows per token.

    A row contributes once per distinct token it contains (set semantics), so
    `'Brazil'_'Poland'` adds 1 to Brazil and 1 to Poland.
    """
    raw = df["string_citizenship_raw_d"].dropna().astype(str)
    tokens = raw.str.findall(TOKEN_RE).map(lambda lst: list(dict.fromkeys(lst)))
    exploded = tokens.explode().dropna()
    return exploded.value_counts()


def main() -> None:
    st.set_page_config(page_title="CV Country Explorer", layout="wide")
    st.title("Cross-Verified — Country Explorer")
    st.caption("Pick a country of citizenship to browse all individuals in the CV database.")

    df = load_cv()
    counts = raw_token_counts(df)

    with st.sidebar:
        st.header("Filters")
        countries = [f"{c}  ({n:,})" for c, n in counts.items()]
        choice = st.selectbox(
            "Citizenship token in string_citizenship_raw_d",
            options=countries,
            index=0,
        )
        country = choice.split("  (")[0]
        match_mode = st.radio(
            "Match mode",
            ["Sole token (only this country)", "Contains token (any row mentioning it)"],
            index=1,
        )

        gender_options = ["(all)"] + sorted(df["gender"].dropna().unique().tolist())
        gender = st.selectbox("Gender", gender_options, index=0)

        occ_options = ["(all)"] + sorted(df["level1_main_occ"].dropna().unique().tolist())
        occ = st.selectbox("Top-level occupation", occ_options, index=0)

        years = df["birth"].dropna()
        if len(years):
            y_min, y_max = int(years.min()), int(years.max())
            year_range = st.slider("Birth year range", y_min, y_max, (y_min, y_max))
        else:
            year_range = None

        sort_col = st.selectbox(
            "Sort by",
            ["wiki_readers_2015_2018", "number_wiki_editions", "ranking_visib_5criteria", "birth", "name"],
            index=0,
        )
        ascending = st.checkbox("Ascending", value=False)
        name_query = st.text_input("Name contains")

    raw = df["string_citizenship_raw_d"].fillna("").astype(str)
    quoted = f"'{country}'"
    if match_mode.startswith("Sole"):
        mask = raw == quoted
    else:
        mask = raw.str.contains(re.escape(quoted), regex=True)
    sub = df[mask].copy()

    if gender != "(all)":
        sub = sub[sub["gender"] == gender]
    if occ != "(all)":
        sub = sub[sub["level1_main_occ"] == occ]
    if year_range is not None:
        sub = sub[(sub["birth"].fillna(year_range[0]) >= year_range[0]) & (sub["birth"].fillna(year_range[1]) <= year_range[1])]
    if name_query.strip():
        sub = sub[sub["name"].fillna("").str.contains(name_query.strip(), case=False, regex=False)]

    if sort_col == "ranking_visib_5criteria":
        sub = sub.sort_values(sort_col, ascending=ascending if ascending else True, na_position="last")
    else:
        sub = sub.sort_values(sort_col, ascending=ascending, na_position="last")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Token", country)
    c2.metric("Rows mentioning token", f"{int(counts.get(country, 0)):,}")
    c3.metric("After filters", f"{len(sub):,}")
    median_readers = sub["wiki_readers_2015_2018"].median() if len(sub) else float("nan")
    c4.metric("Median wiki readers", f"{median_readers:,.0f}" if pd.notna(median_readers) else "—")

    st.dataframe(sub[DISPLAY_COLS], use_container_width=True, height=620)

    csv = sub.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download filtered rows (CSV)",
        data=csv,
        file_name=f"cv_{country}.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    main()
