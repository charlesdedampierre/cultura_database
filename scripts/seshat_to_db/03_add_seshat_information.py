import re
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/datamodels"))

from datamodel_raw import SeshatInformation

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
VALUE = "struct_pack(value_from, value_to, date_from, date_to, fact_type, value_note, date_note) ORDER BY row_id"
GENERAL = "General variables"


def key(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def column_name(variable):
    return re.sub(r"[^a-z0-9]+", "_", variable.lower()).strip("_")


def is_ritual_duration(row):
    return row.variable == "Duration" and row.section != GENERAL


def pick_variable(row, candidates):
    headings = lambda c: {key(c[h]) for h in ("section", "subsection", "subsubsection") if c[h]}
    for wanted in (row.subsection, row.section):
        hits = [c for c in candidates if pd.notna(wanted) and key(wanted) in headings(c)]
        if hits:
            return hits[0]["variable_id"]
    return candidates[0]["variable_id"] if candidates else None


def read_rows():
    rows = pd.read_excel(EQUINOX).rename(columns=COLUMNS)
    for col in ("value_from", "value_to"):
        rows[col] = rows[col].map(lambda v: None if pd.isna(v) else str(v))
    rows.insert(0, "row_id", range(1, len(rows) + 1))
    rows["column_name"] = [
        "ritual_duration" if is_ritual_duration(r) else "ra" if r.variable == "RA" else column_name(r.variable)
        for r in rows.itertuples()
    ]
    return rows


def variable_ids(con, rows):
    by_name = {}
    for c in con.sql("SELECT variable_id, name, section, subsection, subsubsection FROM variable ORDER BY variable_id").df().to_dict("records"):
        by_name.setdefault(key(c["name"]), []).append(c)
    fields = rows[~rows.column_name.isin(["ra", "ritual_duration"])]
    main = fields.groupby(["column_name", "section", "subsection", "variable"], dropna=False).size().reset_index(name="n")
    main = main.sort_values("n").drop_duplicates("column_name", keep="last")
    return {r.column_name: pick_variable(r, by_name.get(key(r.variable), [])) for r in main.itertuples()}


def build_sql(columns):
    variable_columns = ",\n".join(
        f"coalesce(list({VALUE}) FILTER (WHERE column_name = '{c}'), []) AS {c}" for c in columns
    )
    return f"""
    CREATE OR REPLACE TABLE seshat_information AS
    WITH ra AS (
        SELECT polity, map_from_entries(list(struct_pack(k := section, v := names))) AS ra
        FROM (SELECT polity, section, list(value_from ORDER BY row_id) AS names FROM rows WHERE column_name = 'ra' GROUP BY ALL)
        GROUP BY polity
    ), ritual AS (
        SELECT polity, map_from_entries(list(struct_pack(k := subsection, v := vals))) AS ritual_duration
        FROM (SELECT polity, subsection, list({VALUE}) AS vals FROM rows WHERE column_name = 'ritual_duration' GROUP BY ALL)
        GROUP BY polity
    ), fields AS (
        SELECT polity, any_value(nga) AS nga,
        {variable_columns}
        FROM rows GROUP BY polity
    )
    SELECT f.polity, CASE WHEN p.id IS NULL THEN NULL ELSE p END AS seshat_polity, f.nga, coalesce(ra.ra, MAP {{}}) AS ra, coalesce(ritual.ritual_duration, MAP {{}}) AS ritual_duration,
        f.* EXCLUDE (polity, nga)
    FROM fields f LEFT JOIN ra USING (polity) LEFT JOIN ritual USING (polity)
    LEFT JOIN polity p ON p.polity_old_id = f.polity
    ORDER BY f.polity
    """


def main():
    rows = read_rows()
    columns = [c for c in SeshatInformation.model_fields if c not in ("polity", "seshat_polity", "nga", "ra", "ritual_duration")]
    missing = set(rows.column_name) - set(columns) - {"ra", "ritual_duration"}
    assert not missing, f"variables without a SeshatInformation field: {missing}"
    with duckdb.connect(str(DB)) as con:
        con.register("rows", rows)
        con.execute(build_sql(columns))
        con.execute("DROP TABLE IF EXISTS equinox_value")
        for column, variable_id in variable_ids(con, rows).items():
            con.execute(f"COMMENT ON COLUMN seshat_information.{column} IS 'variable_id {variable_id}'")
        stored = con.sql(f"SELECT sum({' + '.join(f'len({c})' for c in columns)}) FROM seshat_information").fetchone()[0]
        ra = con.sql("SELECT sum(len(flatten(map_values(ra)))) FROM seshat_information").fetchone()[0]
        ritual = con.sql("SELECT sum(len(flatten(map_values(ritual_duration)))) FROM seshat_information").fetchone()[0]
        polities = con.sql("SELECT count(*) FROM seshat_information").fetchone()[0]
        orphans = con.sql("SELECT polity FROM seshat_information WHERE seshat_polity IS NULL").fetchall()
    assert stored + ra + ritual == len(rows), f"{stored + ra + ritual} of {len(rows)} rows stored"
    print(f"{polities} polities, {len(rows)} values written to seshat_information in {DB.name}")
    print(f"polities missing from the polity table: {[o[0] for o in orphans]}")


if __name__ == "__main__":
    main()
