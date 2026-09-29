import re
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CODEBOOK = ROOT / "data/seshat/Legacy Codebook (Equinox).txt"
DB = ROOT / "data/seshat/seshat.duckdb"
TOC_END = 178
HEADING_LOOKAHEAD = 6
VARIABLE_LINE = re.compile(r"\s*♠\s*(.+?)\s*♣\s*♥\s*(.*)")


def read_toc(lines):
    toc = []
    for line in lines[2:TOC_END]:
        m = re.match(r"^(\d+(?:\.\d+)*) (.+)$", line)
        if m:
            toc.append((m.group(1), m.group(2).strip()))
    return toc


def hierarchy(number, titles):
    parts = number.split(".")
    levels = [titles[".".join(parts[:i])] for i in range(1, len(parts) + 1)]
    return levels + [None] * (4 - len(levels))


def parse_variables(lines, toc):
    titles = dict(toc)
    ptr, heading, variables = 0, None, []
    for i, line in enumerate(lines[TOC_END:], start=TOC_END + 1):
        text = line.strip()
        match = next((k for k in range(ptr, min(ptr + HEADING_LOOKAHEAD, len(toc))) if text == toc[k][1]), None)
        if match is not None:
            ptr, heading = match + 1, toc[match][0]
            continue
        m = VARIABLE_LINE.match(line)
        if m and heading and not heading.startswith("1"):
            part, section, subsection, subsubsection = hierarchy(heading, titles)[:4]
            variables.append({
                "name": m.group(1).strip(),
                "definition": re.sub(r"\s+", " ", m.group(2)).strip() or None,
                "notes": [],
                "heading_number": heading,
                "part": part,
                "section": section,
                "subsection": subsection,
                "subsubsection": subsubsection,
                "codebook_line": i,
            })
        elif variables and text and heading and not heading.startswith("1"):
            variables[-1]["notes"].append(text)
    for v in variables:
        v["notes"] = "\n".join(v["notes"]) or None
    return variables


def main():
    lines = CODEBOOK.read_text().splitlines()
    variables = pd.DataFrame(parse_variables(lines, read_toc(lines)))
    variables.insert(0, "variable_id", range(1, len(variables) + 1))
    with duckdb.connect(str(DB)) as con:
        con.execute("CREATE OR REPLACE TABLE variable AS SELECT * FROM variables")
        print(con.sql("SELECT part, count(*) AS n FROM variable GROUP BY part ORDER BY min(variable_id)"))
    print(f"{len(variables)} variables written to {DB.name}")


if __name__ == "__main__":
    main()
