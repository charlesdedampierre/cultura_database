"""28b — Add missing countries (North America, Latin America, Sub-Saharan Africa,
Oceania, Southeast Asia, plus small European/Asian territories) to the
`regions` table.

Mirrors `enhance_db/src/bin/28b_add_missing_regions.rs`.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import DB_PATH, log, open_db, parse_run_mode, table_exists, transaction


# (macro_region, region, iso_country_name, iso_a3, start_year, end_year)
NEW_REGION_DATA: list[tuple[str, str, str, str, int, int | None]] = [
    # North America
    ("North America", "North America", "United States", "USA", -10000, None),
    ("North America", "North America", "Canada", "CAN", -10000, None),
    ("North America", "North America", "Bermuda", "BMU", -10000, None),
    ("North America", "North America", "Saint Pierre and Miquelon", "SPM", -10000, None),
    ("North America", "North America", "Greenland", "GRL", -10000, None),
    # Latin America - Central America
    ("Latin America", "Central America", "Mexico", "MEX", -10000, None),
    ("Latin America", "Central America", "Guatemala", "GTM", -10000, None),
    ("Latin America", "Central America", "El Salvador", "SLV", -10000, None),
    ("Latin America", "Central America", "Honduras", "HND", -10000, None),
    ("Latin America", "Central America", "Nicaragua", "NIC", -10000, None),
    ("Latin America", "Central America", "Costa Rica", "CRI", -10000, None),
    ("Latin America", "Central America", "Panama", "PAN", -10000, None),
    ("Latin America", "Central America", "Belize", "BLZ", -10000, None),
    # Latin America - Caribbean
    ("Latin America", "Caribbean", "Cuba", "CUB", -10000, None),
    ("Latin America", "Caribbean", "Jamaica", "JAM", -10000, None),
    ("Latin America", "Caribbean", "Haiti", "HTI", -10000, None),
    ("Latin America", "Caribbean", "Dominican Republic", "DOM", -10000, None),
    ("Latin America", "Caribbean", "Trinidad and Tobago", "TTO", -10000, None),
    ("Latin America", "Caribbean", "Barbados", "BRB", -10000, None),
    ("Latin America", "Caribbean", "The Bahamas", "BHS", -10000, None),
    ("Latin America", "Caribbean", "Antigua and Barbuda", "ATG", -10000, None),
    ("Latin America", "Caribbean", "Dominica", "DMA", -10000, None),
    ("Latin America", "Caribbean", "Grenada", "GRD", -10000, None),
    ("Latin America", "Caribbean", "Saint Kitts and Nevis", "KNA", -10000, None),
    ("Latin America", "Caribbean", "Saint Lucia", "LCA", -10000, None),
    ("Latin America", "Caribbean", "Saint Vincent and the Grenadines", "VCT", -10000, None),
    ("Latin America", "Caribbean", "Puerto Rico", "PRI", -10000, None),
    ("Latin America", "Caribbean", "Cayman Islands", "CYM", -10000, None),
    ("Latin America", "Caribbean", "Anguilla", "AIA", -10000, None),
    ("Latin America", "Caribbean", "British Virgin Islands", "VGB", -10000, None),
    ("Latin America", "Caribbean", "Guadeloupe", "GLP", -10000, None),
    ("Latin America", "Caribbean", "Montserrat", "MSR", -10000, None),
    ("Latin America", "Caribbean", "Martinique", "MTQ", -10000, None),
    ("Latin America", "Caribbean", "United States Virgin Islands", "VIR", -10000, None),
    ("Latin America", "Caribbean", "Turks and Caicos Islands", "TCA", -10000, None),
    ("Latin America", "Caribbean", "Caribbean Netherlands", "BES", -10000, None),
    ("Latin America", "Caribbean", "Aruba", "ABW", -10000, None),
    ("Latin America", "Caribbean", "Curaçao", "CUW", -10000, None),
    ("Latin America", "Caribbean", "Saint Barthélemy", "BLM", -10000, None),
    ("Latin America", "Caribbean", "Sint Maarten", "SXM", -10000, None),
    # Latin America - South America
    ("Latin America", "South America", "Brazil", "BRA", -10000, None),
    ("Latin America", "South America", "Argentina", "ARG", -10000, None),
    ("Latin America", "South America", "Peru", "PER", -10000, None),
    ("Latin America", "South America", "Chile", "CHL", -10000, None),
    ("Latin America", "South America", "Uruguay", "URY", -10000, None),
    ("Latin America", "South America", "Colombia", "COL", -10000, None),
    ("Latin America", "South America", "Venezuela", "VEN", -10000, None),
    ("Latin America", "South America", "Ecuador", "ECU", -10000, None),
    ("Latin America", "South America", "Bolivia", "BOL", -10000, None),
    ("Latin America", "South America", "Paraguay", "PRY", -10000, None),
    ("Latin America", "South America", "Suriname", "SUR", -10000, None),
    ("Latin America", "South America", "Guyana", "GUY", -10000, None),
    ("Latin America", "South America", "French Guiana", "GUF", -10000, None),
    ("Latin America", "South America", "Falkland Islands", "FLK", -10000, None),
    # Sub-Saharan Africa - West
    ("Sub-Saharan Africa", "West Africa", "Nigeria", "NGA", -10000, None),
    ("Sub-Saharan Africa", "West Africa", "Ghana", "GHA", -10000, None),
    ("Sub-Saharan Africa", "West Africa", "Cameroon", "CMR", -10000, None),
    ("Sub-Saharan Africa", "West Africa", "Senegal", "SEN", -10000, None),
    ("Sub-Saharan Africa", "West Africa", "Ivory Coast", "CIV", -10000, None),
    ("Sub-Saharan Africa", "West Africa", "Sierra Leone", "SLE", -10000, None),
    ("Sub-Saharan Africa", "West Africa", "Mali", "MLI", -10000, None),
    ("Sub-Saharan Africa", "West Africa", "Benin", "BEN", -10000, None),
    ("Sub-Saharan Africa", "West Africa", "Togo", "TGO", -10000, None),
    ("Sub-Saharan Africa", "West Africa", "Niger", "NER", -10000, None),
    ("Sub-Saharan Africa", "West Africa", "Burkina Faso", "BFA", -10000, None),
    ("Sub-Saharan Africa", "West Africa", "The Gambia", "GMB", -10000, None),
    ("Sub-Saharan Africa", "West Africa", "Guinea-Bissau", "GNB", -10000, None),
    ("Sub-Saharan Africa", "West Africa", "Cape Verde", "CPV", -10000, None),
    ("Sub-Saharan Africa", "West Africa", "Liberia", "LBR", -10000, None),
    ("Sub-Saharan Africa", "West Africa", "Guinea", "GIN", -10000, None),
    ("Sub-Saharan Africa", "West Africa", "São Tomé and Príncipe", "STP", -10000, None),
    ("Sub-Saharan Africa", "West Africa", "Mauritania", "MRT", -10000, None),
    # Sub-Saharan Africa - East
    ("Sub-Saharan Africa", "East Africa", "Uganda", "UGA", -10000, None),
    ("Sub-Saharan Africa", "East Africa", "Kenya", "KEN", -10000, None),
    ("Sub-Saharan Africa", "East Africa", "Tanzania", "TZA", -10000, None),
    ("Sub-Saharan Africa", "East Africa", "Ethiopia", "ETH", -10000, None),
    ("Sub-Saharan Africa", "East Africa", "Rwanda", "RWA", -10000, None),
    ("Sub-Saharan Africa", "East Africa", "South Sudan", "SSD", -10000, None),
    ("Sub-Saharan Africa", "East Africa", "Somalia", "SOM", -10000, None),
    ("Sub-Saharan Africa", "East Africa", "Mozambique", "MOZ", -10000, None),
    ("Sub-Saharan Africa", "East Africa", "Malawi", "MWI", -10000, None),
    ("Sub-Saharan Africa", "East Africa", "Madagascar", "MDG", -10000, None),
    ("Sub-Saharan Africa", "East Africa", "Zambia", "ZMB", -10000, None),
    ("Sub-Saharan Africa", "East Africa", "Zimbabwe", "ZWE", -10000, None),
    ("Sub-Saharan Africa", "East Africa", "Burundi", "BDI", -10000, None),
    ("Sub-Saharan Africa", "East Africa", "Eritrea", "ERI", -10000, None),
    ("Sub-Saharan Africa", "East Africa", "Djibouti", "DJI", -10000, None),
    ("Sub-Saharan Africa", "East Africa", "Comoros", "COM", -10000, None),
    ("Sub-Saharan Africa", "East Africa", "Seychelles", "SYC", -10000, None),
    ("Sub-Saharan Africa", "East Africa", "Mauritius", "MUS", -10000, None),
    ("Sub-Saharan Africa", "East Africa", "Sudan", "SDN", -10000, None),
    ("Sub-Saharan Africa", "East Africa", "Réunion", "REU", -10000, None),
    ("Sub-Saharan Africa", "East Africa", "Mayotte", "MYT", -10000, None),
    # Sub-Saharan Africa - Central
    ("Sub-Saharan Africa", "Central Africa", "Democratic Republic of the Congo", "COD", -10000, None),
    ("Sub-Saharan Africa", "Central Africa", "Republic of the Congo", "COG", -10000, None),
    ("Sub-Saharan Africa", "Central Africa", "Central African Republic", "CAF", -10000, None),
    ("Sub-Saharan Africa", "Central Africa", "Chad", "TCD", -10000, None),
    ("Sub-Saharan Africa", "Central Africa", "Gabon", "GAB", -10000, None),
    ("Sub-Saharan Africa", "Central Africa", "Angola", "AGO", -10000, None),
    ("Sub-Saharan Africa", "Central Africa", "Equatorial Guinea", "GNQ", -10000, None),
    # Sub-Saharan Africa - Southern
    ("Sub-Saharan Africa", "Southern Africa", "South Africa", "ZAF", -10000, None),
    ("Sub-Saharan Africa", "Southern Africa", "Botswana", "BWA", -10000, None),
    ("Sub-Saharan Africa", "Southern Africa", "Namibia", "NAM", -10000, None),
    ("Sub-Saharan Africa", "Southern Africa", "Eswatini", "SWZ", -10000, None),
    ("Sub-Saharan Africa", "Southern Africa", "Lesotho", "LSO", -10000, None),
    # Asia - Southeast Asia
    ("Asia", "Southeast Asia", "Indonesia", "IDN", -10000, None),
    ("Asia", "Southeast Asia", "Thailand", "THA", -10000, None),
    ("Asia", "Southeast Asia", "Malaysia", "MYS", -10000, None),
    ("Asia", "Southeast Asia", "Philippines", "PHL", -10000, None),
    ("Asia", "Southeast Asia", "Vietnam", "VNM", -10000, None),
    ("Asia", "Southeast Asia", "Myanmar", "MMR", -10000, None),
    ("Asia", "Southeast Asia", "Singapore", "SGP", -10000, None),
    ("Asia", "Southeast Asia", "Cambodia", "KHM", -10000, None),
    ("Asia", "Southeast Asia", "Timor-Leste", "TLS", -10000, None),
    ("Asia", "Southeast Asia", "Laos", "LAO", -10000, None),
    ("Asia", "Southeast Asia", "Brunei", "BRN", -10000, None),
    # Asia - Central Asia
    ("Asia", "Central Asia", "Kazakhstan", "KAZ", -10000, None),
    ("Asia", "Central Asia", "Tajikistan", "TJK", -10000, None),
    # Asia - Chinese World additions
    ("Asia", "Chinese World", "Hong Kong", "HKG", -10000, None),
    ("Asia", "Chinese World", "Macau", "MAC", -10000, None),
    # Asia - Indian World additions
    ("Asia", "Indian World", "Maldives", "MDV", -10000, None),
    ("Asia", "Indian World", "Bhutan", "BTN", -10000, None),
    # Eastern Europe - Caucasus
    ("Eastern Europe", "Caucasus", "Georgia", "GEO", -10000, None),
    ("Eastern Europe", "Caucasus", "Armenia", "ARM", -10000, None),
    # Eastern Europe - East Slavic additions
    ("Eastern Europe", "East Slavic", "Moldova", "MDA", 500, None),
    ("Eastern Europe", "East Slavic", "Soviet Union", "SUN", 500, None),
    # Western Europe additions
    ("Western Europe", "Italy", "Vatican City", "VAT", 500, None),
    ("Western Europe", "Italy", "San Marino", "SMR", 500, None),
    ("Western Europe", "Italy", "Malta", "MLT", 500, None),
    ("Western Europe", "Low countries", "Luxembourg", "LUX", 500, None),
    ("Western Europe", "German world", "Liechtenstein", "LIE", 500, None),
    ("Western Europe", "France", "Monaco", "MCO", 500, None),
    ("Western Europe", "France", "Andorra", "AND", 500, None),
    ("Western Europe", "British Islands", "Gibraltar", "GIB", 500, None),
    ("Western Europe", "British Islands", "Isle of Man", "IMN", 500, None),
    ("Western Europe", "British Islands", "Guernsey", "GGY", 500, None),
    ("Western Europe", "Nordic countries", "Faroe Islands", "FRO", 500, None),
    ("Western Europe", "Nordic countries", "Svalbard and Jan Mayen", "SJM", 500, None),
    # Oceania
    ("Oceania", "Australia and New Zealand", "Australia", "AUS", -10000, None),
    ("Oceania", "Australia and New Zealand", "New Zealand", "NZL", -10000, None),
    ("Oceania", "Australia and New Zealand", "Norfolk Island", "NFK", -10000, None),
    ("Oceania", "Australia and New Zealand", "Cocos (Keeling) Islands", "CCK", -10000, None),
    ("Oceania", "Australia and New Zealand", "Christmas Island", "CXR", -10000, None),
    ("Oceania", "Melanesia", "Papua New Guinea", "PNG", -10000, None),
    ("Oceania", "Melanesia", "Fiji", "FJI", -10000, None),
    ("Oceania", "Melanesia", "Solomon Islands", "SLB", -10000, None),
    ("Oceania", "Melanesia", "Vanuatu", "VUT", -10000, None),
    ("Oceania", "Melanesia", "New Caledonia", "NCL", -10000, None),
    ("Oceania", "Polynesia", "Tonga", "TON", -10000, None),
    ("Oceania", "Polynesia", "Samoa", "WSM", -10000, None),
    ("Oceania", "Polynesia", "Cook Islands", "COK", -10000, None),
    ("Oceania", "Polynesia", "Niue", "NIU", -10000, None),
    ("Oceania", "Polynesia", "French Polynesia", "PYF", -10000, None),
    ("Oceania", "Polynesia", "American Samoa", "ASM", -10000, None),
    ("Oceania", "Polynesia", "Tokelau", "TKL", -10000, None),
    ("Oceania", "Polynesia", "Pitcairn Islands", "PCN", -10000, None),
    ("Oceania", "Polynesia", "Wallis and Futuna", "WLF", -10000, None),
    ("Oceania", "Polynesia", "Tuvalu", "TUV", -10000, None),
    ("Oceania", "Micronesia", "Federated States of Micronesia", "FSM", -10000, None),
    ("Oceania", "Micronesia", "Kiribati", "KIR", -10000, None),
    ("Oceania", "Micronesia", "Nauru", "NRU", -10000, None),
    ("Oceania", "Micronesia", "Palau", "PLW", -10000, None),
    ("Oceania", "Micronesia", "Marshall Islands", "MHL", -10000, None),
    ("Oceania", "Micronesia", "Guam", "GUM", -10000, None),
    ("Oceania", "Micronesia", "Northern Mariana Islands", "MNP", -10000, None),
    # Remaining territories
    ("Sub-Saharan Africa", "Southern Africa", "Saint Helena, Ascension and Tristan da Cunha", "SHN", -10000, None),
    ("Oceania", "Australia and New Zealand", "French Southern and Antarctic Lands", "ATF", -10000, None),
    ("Middle-East and Africa (MENA)", "Arabic world", "Western Sahara", "ESH", -10000, None),
    ("Middle-East and Africa (MENA)", "Arabic world", "Qatar", "QAT", -10000, None),
]


def run(conn: sqlite3.Connection) -> None:
    log("[DB] 28b: Add missing regions...")
    existing_pairs = set()
    for iso, region in conn.execute("SELECT iso_a3, region FROM regions"):
        existing_pairs.add((iso, region))

    inserted = 0
    skipped = 0
    with transaction(conn):
        ins = conn.cursor()
        for macro_r, region, country, iso, start, end in NEW_REGION_DATA:
            if (iso, region) in existing_pairs:
                skipped += 1
                continue
            ins.execute(
                "INSERT INTO regions (macro_region, region, iso_country_name, iso_a3, "
                "start_year, end_year) VALUES (?, ?, ?, ?, ?, ?)",
                (macro_r, region, country, iso, start, end),
            )
            existing_pairs.add((iso, region))
            inserted += 1
    log(f"[28b] Inserted {inserted}, skipped {skipped} duplicates")

    if table_exists(conn, "individuals_countries"):
        unmapped = conn.execute(
            """
            SELECT DISTINCT ic.iso_country_name, ic.iso_a3_code, COUNT(*) as cnt
            FROM individuals_countries ic
            LEFT JOIN regions r ON ic.iso_a3_code = r.iso_a3
            WHERE r.iso_a3 IS NULL
            GROUP BY ic.iso_country_name, ic.iso_a3_code
            ORDER BY cnt DESC
            """
        ).fetchall()
        if unmapped:
            log(f"[28b] WARNING: {len(unmapped)} countries still unmapped:")
            for n, iso, c in unmapped:
                log(f"[28b]   {n} ({iso}) -> {c}")
        else:
            log("[28b] All countries in individuals_countries are mapped")


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with open_db(db) as conn:
            conn.execute(
                """
                CREATE TABLE regions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    macro_region TEXT, region TEXT, iso_country_name TEXT,
                    iso_a3 TEXT, start_year INTEGER, end_year INTEGER
                )
                """
            )
            conn.execute(
                "INSERT INTO regions (macro_region, region, iso_country_name, iso_a3, start_year, end_year) "
                "VALUES ('Western Europe', 'France', 'France', 'FRA', 500, NULL)"
            )
            conn.commit()
            run(conn)
            log(f"[sample] regions count: {conn.execute('SELECT COUNT(*) FROM regions').fetchone()[0]}")
            log(f"[sample] distinct iso: {conn.execute('SELECT COUNT(DISTINCT iso_a3) FROM regions').fetchone()[0]}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db(DB_PATH) as conn:
            run(conn)
    else:
        _sample_main()
