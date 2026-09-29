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
DB = ROOT / "data/seshat/seshat.duckdb"


def main():
    polities = pd.read_csv(POLITIES, sep="|")
    polities.columns = [c.lower() for c in polities.columns]
    polities = polities.rename(columns={code: f"{code} ({meaning})" for code, meaning in FLAGS.items()})
    polities = polities[["polity_long_name"] + [c for c in polities.columns if c != "polity_long_name"]]
    assert polities.id.is_unique and polities.polity_new_id.is_unique and polities.polity_old_id.is_unique
    with duckdb.connect(str(DB)) as con:
        con.execute("CREATE OR REPLACE TABLE polity AS SELECT * FROM polities ORDER BY id")
    print(f"{len(polities)} polities written to {DB.name}")


if __name__ == "__main__":
    main()
