"""Build data/similar_databases/cross_verified.duckdb, the table individuals, from the UTF-8 copy of the cross-verified database CSV."""

from csv_to_duckdb import R, SIMILAR, build

SOURCE = SIMILAR / "cross-verified-database" / "cross-verified-database.utf8.csv.gz"

if __name__ == "__main__":
    build(SOURCE, R.CrossVerifiedPerson, SIMILAR / "cross_verified.duckdb")
