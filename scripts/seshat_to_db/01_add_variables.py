import re
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CODEBOOK = ROOT / "data/seshat/Legacy Codebook (Equinox).txt"
EQUINOX = ROOT / "data/seshat/Equinox2020.05.2023.xlsx"
DB = ROOT / "data/seshat/seshat.duckdb"
TOC_END = 178
HEADING_LOOKAHEAD = 6
GENERAL = "General variables"
VARIABLE_LINE = re.compile(r"\s*♠\s*(.+?)\s*♣\s*♥\s*(.*)")


def key(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def read_toc(lines):
    toc = []
    for line in lines[2:TOC_END]:
        m = re.match(r"^(\d+(?:\.\d+)*) (.+)$", line)
        if m:
            toc.append((m.group(1), m.group(2).strip()))
    return toc


def headings(number, titles):
    parts = number.split(".")
    return {key(titles[".".join(parts[:i])]) for i in range(1, len(parts) + 1)}


def parse_codebook(lines, toc):
    titles = dict(toc)
    ptr, heading, variables = 0, None, []
    for line in lines[TOC_END:]:
        text = line.strip()
        match = next((k for k in range(ptr, min(ptr + HEADING_LOOKAHEAD, len(toc))) if text == toc[k][1]), None)
        if match is not None:
            ptr, heading = match + 1, toc[match][0]
            continue
        m = VARIABLE_LINE.match(line)
        if m and heading and not heading.startswith("1"):
            variables.append({
                "name": m.group(1).strip(),
                "definition": re.sub(r"\s+", " ", m.group(2)).strip() or None,
                "notes": [],
                "headings": headings(heading, titles),
            })
        elif variables and text and heading and not heading.startswith("1"):
            variables[-1]["notes"].append(text)
    for v in variables:
        v["notes"] = "\n".join(v["notes"]) or None
    return variables


def equinox_variables():
    rows = pd.read_excel(EQUINOX, usecols=["Section", "Subsection", "Variable"])
    rows.columns = ["section", "subsection", "name"]
    ritual = (rows.name == "Duration") & (rows.section != GENERAL)
    rows["group"] = rows.subsection.where(ritual)
    counts = rows.groupby(["section", "name", "group", "subsection"], dropna=False).size().reset_index(name="n")
    counts = counts.sort_values(["subsection", "n"], na_position="first").drop_duplicates(["section", "name", "group"], keep="last")
    return counts[["section", "subsection", "name"]].sort_values(["section", "subsection", "name"], na_position="first")


def definition_for(row, codebook):
    candidates = [c for c in codebook if key(c["name"]) == key(row.name)]
    for wanted in (row.subsection, row.section):
        hits = [c for c in candidates if pd.notna(wanted) and key(wanted) in c["headings"]]
        if hits:
            return hits[0]
    return candidates[0] if candidates else {"definition": None, "notes": None}


def main():
    lines = CODEBOOK.read_text().splitlines()
    codebook = parse_codebook(lines, read_toc(lines))
    variables = equinox_variables()
    found = [definition_for(r, codebook) for r in variables.itertuples()]
    variables["definition"] = [f["definition"] for f in found]
    variables["notes"] = [f["notes"] for f in found]
    assert not variables.duplicated(["section", "subsection", "name"]).any()
    with duckdb.connect(str(DB)) as con:
        con.execute("CREATE OR REPLACE TABLE variable AS SELECT * FROM variables")
        print(con.sql("SELECT section, count(*) AS n, count(definition) AS with_definition FROM variable GROUP BY 1 ORDER BY 1"))
    print(f"{len(variables)} Equinox variables written to {DB.name}")


if __name__ == "__main__":
    main()
