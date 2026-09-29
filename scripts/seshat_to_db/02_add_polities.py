import re
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
FLAGS = {
    "g": "General Variables",
    "sc": "Social Complexity Variables",
    "wf": "Warfare Variables",
    "rt": "Religion Variables",
    "hs": "Human Sacrifice",
    "cc": "Crisis Consequences",
    "pt": "Power Transition",
    "in": "Instability Events",
}
POLITIES = ROOT / "data/seshat/polities_20260929_110619.csv"
CLIOPATRIA = ROOT / "data/cliopatria_data/cliopatria_V2/cliopatria_polities_only_v3.geojson"
DB = ROOT / "data/seshat/seshat.duckdb"


def cliopatria_seshat_ids():
    fields = re.findall(r'"SeshatID":\s*"([^"]*)"', CLIOPATRIA.read_text())
    return {i.strip() for f in fields for i in f.split(";") if i.strip()}


def main():
    polities = pd.read_csv(POLITIES, sep="|")
    polities.columns = [c.lower() for c in polities.columns]
    polities = polities.rename(columns={code: f"{code} ({meaning})" for code, meaning in FLAGS.items()})
    polities = polities[["polity_long_name"] + [c for c in polities.columns if c != "polity_long_name"]]
    polities["link_to_cliopatria"] = polities.polity_new_id.isin(cliopatria_seshat_ids())
    assert polities.id.is_unique and polities.polity_new_id.is_unique and polities.polity_old_id.is_unique
    with duckdb.connect(str(DB)) as con:
        con.execute("CREATE OR REPLACE TABLE polity AS SELECT * FROM polities ORDER BY id")
    print(f"{len(polities)} polities written to {DB.name}, {polities.link_to_cliopatria.sum()} linked to Cliopatria")


if __name__ == "__main__":
    main()
