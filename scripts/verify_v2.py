"""Every table in the database has exactly the columns and types its model declares."""

import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path("scripts").resolve()))
sys.path.insert(0, str(Path(".").resolve()))
import build_v2 as B
import datamodel_in_duckdb as M

con = duckdb.connect("data/humans_clean_v2.duckdb", read_only=True)
tables = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
problems = []

if tables != set(M.TABLES):
    problems.append(f"tables differ: extra {tables - set(M.TABLES)}, missing {set(M.TABLES) - tables}")

for name, model in M.TABLES.items():
    if name not in tables:
        continue
    actual = {r[0]: r[1] for r in con.execute(f'DESCRIBE "{name}"').fetchall()}
    expected = {f: B.duck_type(i.annotation) for f, i in model.model_fields.items()}
    if list(actual) != list(expected):
        problems.append(f"{name}: columns {list(actual)} != {list(expected)}")
        continue
    for column, want in expected.items():
        got = actual[column]
        if got.replace('"', "") != want.replace('"', ""):
            problems.append(f"{name}.{column}\n      model {want}\n      table {got}")

print(f"{len(M.TABLES)} tables, {sum(len(m.model_fields) for m in M.TABLES.values())} columns checked")
for p in problems:
    print("   MISMATCH", p)
print("\n" + ("every column matches its model" if not problems else f"{len(problems)} mismatches"))

# and the values themselves validate, not only the column types
print()
for name, model in M.TABLES.items():
    cur = con.execute(f'SELECT * FROM "{name}" USING SAMPLE 50 ROWS')
    columns = [d[0] for d in cur.description]
    rows = [dict(zip(columns, r)) for r in cur.fetchall()]
    bad = []
    for row in rows:
        try:
            model.model_validate(row)
        except Exception as error:
            bad.append(str(error).splitlines()[1] if len(str(error).splitlines()) > 1 else str(error))
    print(f"   {name:24} {len(rows) - len(bad):>3}/{len(rows)} rows validate" + (f"  — {bad[0][:80]}" if bad else ""))
