"""Compare Cross-Verified database vs Cultura on individual & date coverage."""

from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[1]
CV_CSV = ROOT / "data/similar_databases/cross-verified-database/cross-verified-database.utf8.csv.gz"
DB = ROOT / "data/humans_clean.sqlite3"

con = duckdb.connect()
con.execute("INSTALL sqlite; LOAD sqlite;")
con.execute(f"ATTACH '{DB}' AS cult (TYPE sqlite, READ_ONLY);")

print("Loading CV CSV into DuckDB...")
con.execute(f"""
    CREATE TEMP TABLE cv AS
    SELECT
        wikidata_code AS qid,
        TRY_CAST(birth AS INTEGER) AS birth_year,
        TRY_CAST(death AS INTEGER) AS death_year
    FROM read_csv_auto('{CV_CSV}', header=true, ignore_errors=true);
""")

cv_total = con.execute("SELECT COUNT(*) FROM cv;").fetchone()[0]
cv_with_qid = con.execute("SELECT COUNT(*) FROM cv WHERE qid IS NOT NULL AND qid <> '';").fetchone()[0]
cv_birth = con.execute("SELECT COUNT(*) FROM cv WHERE birth_year IS NOT NULL;").fetchone()[0]
cv_death = con.execute("SELECT COUNT(*) FROM cv WHERE death_year IS NOT NULL;").fetchone()[0]

print(f"\nCV total rows         : {cv_total:>10,}")
print(f"CV rows with QID      : {cv_with_qid:>10,}")
print(f"CV rows with birth    : {cv_birth:>10,}")
print(f"CV rows with death    : {cv_death:>10,}")

print("\nMaterializing Cultura individuals slice...")
con.execute("""
    CREATE TEMP TABLE cult_ind AS
    SELECT wikidata_id AS qid,
           birthdate,
           deathdate,
           floruit_date
    FROM cult.individuals;
""")
cult_total = con.execute("SELECT COUNT(*) FROM cult_ind;").fetchone()[0]
print(f"Cultura individuals   : {cult_total:>10,}")

# 1. Individuals in CV but not in Cultura (by QID match)
in_cv_not_cult = con.execute("""
    SELECT COUNT(*) FROM cv
    WHERE qid IS NOT NULL AND qid <> ''
      AND qid NOT IN (SELECT qid FROM cult_ind);
""").fetchone()[0]
in_both = cv_with_qid - in_cv_not_cult

print(f"\n--- Individual coverage ---")
print(f"CV ∩ Cultura (matched on QID)            : {in_both:>10,}")
print(f"CV individuals NOT in Cultura            : {in_cv_not_cult:>10,}")

# 2. Date coverage on the matched intersection
print("\nJoining CV ↔ Cultura on QID for date comparison...")
con.execute("""
    CREATE TEMP TABLE matched AS
    SELECT cv.qid,
           cv.birth_year,
           cv.death_year,
           ci.birthdate,
           ci.deathdate,
           ci.floruit_date
    FROM cv
    JOIN cult_ind ci USING (qid)
    WHERE cv.qid IS NOT NULL AND cv.qid <> '';
""")

matched_n = con.execute("SELECT COUNT(*) FROM matched;").fetchone()[0]
print(f"Matched rows: {matched_n:,}")

birth_only_in_cv = con.execute("""
    SELECT COUNT(*) FROM matched
    WHERE birth_year IS NOT NULL AND (birthdate IS NULL OR birthdate = '');
""").fetchone()[0]

death_only_in_cv = con.execute("""
    SELECT COUNT(*) FROM matched
    WHERE death_year IS NOT NULL AND (deathdate IS NULL OR deathdate = '');
""").fetchone()[0]

# CV has birth but Cultura has neither birthdate nor floruit_date
birth_no_birth_no_floruit = con.execute("""
    SELECT COUNT(*) FROM matched
    WHERE birth_year IS NOT NULL
      AND (birthdate IS NULL OR birthdate = '')
      AND (floruit_date IS NULL OR floruit_date = '');
""").fetchone()[0]

# CV has death but Cultura has neither deathdate nor floruit_date
death_no_death_no_floruit = con.execute("""
    SELECT COUNT(*) FROM matched
    WHERE death_year IS NOT NULL
      AND (deathdate IS NULL OR deathdate = '')
      AND (floruit_date IS NULL OR floruit_date = '');
""").fetchone()[0]

# CV has any year, Cultura has none of birth/death/floruit
any_in_cv_none_in_cult = con.execute("""
    SELECT COUNT(*) FROM matched
    WHERE (birth_year IS NOT NULL OR death_year IS NOT NULL)
      AND (birthdate    IS NULL OR birthdate    = '')
      AND (deathdate    IS NULL OR deathdate    = '')
      AND (floruit_date IS NULL OR floruit_date = '');
""").fetchone()[0]

# Counterpart for context: how many matched have NO date in Cultura at all
no_date_in_cult = con.execute("""
    SELECT COUNT(*) FROM matched
    WHERE (birthdate    IS NULL OR birthdate    = '')
      AND (deathdate    IS NULL OR deathdate    = '')
      AND (floruit_date IS NULL OR floruit_date = '');
""").fetchone()[0]

print(f"\n--- Date coverage on matched individuals ---")
print(f"CV has birth, Cultura birthdate is NULL  : {birth_only_in_cv:>10,}")
print(f"CV has death, Cultura deathdate is NULL  : {death_only_in_cv:>10,}")
print(f"CV has birth, Cultura no birthdate AND no floruit: {birth_no_birth_no_floruit:>10,}")
print(f"CV has death, Cultura no deathdate AND no floruit: {death_no_death_no_floruit:>10,}")
print(f"Cultura has NO date at all (matched rows): {no_date_in_cult:>10,}")
print(f"  → of which CV provides a year (birth or death): {any_in_cv_none_in_cult:>10,}")
