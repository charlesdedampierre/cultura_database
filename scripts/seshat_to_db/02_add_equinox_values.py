import re
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EQUINOX = ROOT / "data/seshat/Equinox2020.05.2023.xlsx"
DB = ROOT / "data/seshat/seshat.duckdb"
COLUMNS = {
    "NGA": "nga",
    "Polity": "polity",
    "Section": "section",
    "Subsection": "subsection",
    "Variable": "variable",
    "Value.From": "value_from",
    "Value.To": "value_to",
    "Date.From": "date_from",
    "Date.To": "date_to",
    "Fact.Type": "fact_type",
    "Value.Note": "value_note",
    "Date.Note": "date_note",
}


def key(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def pick_variable(row, candidates):
    headings = lambda c: {key(c[h]) for h in ("section", "subsection", "subsubsection") if c[h]}
    for wanted in (row.subsection, row.section):
        hits = [c for c in candidates if pd.notna(wanted) and key(wanted) in headings(c)]
        if hits:
            return hits[0]["variable_id"]
    return candidates[0]["variable_id"] if candidates else None


def main():
    values = pd.read_excel(EQUINOX).rename(columns=COLUMNS)
    for col in ("value_from", "value_to"):
        values[col] = values[col].map(lambda v: None if pd.isna(v) else str(v))
    values.insert(0, "value_id", range(1, len(values) + 1))
    with duckdb.connect(str(DB)) as con:
        codebook = con.sql("SELECT variable_id, name, section, subsection, subsubsection FROM variable ORDER BY variable_id").df()
        by_name = {}
        for c in codebook.to_dict("records"):
            by_name.setdefault(key(c["name"]), []).append(c)
        pairs = values[["section", "subsection", "variable"]].drop_duplicates()
        pairs["variable_id"] = [pick_variable(r, by_name.get(key(r.variable), [])) for r in pairs.itertuples()]
        values = values.merge(pairs, on=["section", "subsection", "variable"], how="left")
        values["variable_id"] = values["variable_id"].astype("Int64")
        polities = values[["polity", "nga"]].drop_duplicates().sort_values("polity")
        assert polities.polity.is_unique
        con.execute("CREATE OR REPLACE TABLE polity AS SELECT * FROM polities")
        con.execute("CREATE OR REPLACE TABLE equinox_value AS SELECT * FROM values ORDER BY value_id")
        unmatched = values[values.variable_id.isna()].variable.unique()
    print(f"{len(values)} values for {len(polities)} polities written to {DB.name}")
    print(f"unmatched to the codebook: {list(unmatched)}")


if __name__ == "__main__":
    main()
