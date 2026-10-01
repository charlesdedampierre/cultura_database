"""
Reverse geocode nationalities lat/lon to find modern countries.
Saves results as JSON in data/all_humans/nationality_modern_countries.json
"""

import sqlite3
import json
import os
import sys
import subprocess

# Keep process alive
try:
    subprocess.Popen(["caffeinate"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except FileNotFoundError:
    pass  # Not on macOS

import reverse_geocoder as rg

DB_PATH = "data/humans_clean.sqlite3"
OUTPUT_PATH = "data/all_humans/nationality_modern_countries.json"
TASK_LOG = "task.log"

# ISO alpha-2 to alpha-3 mapping
ALPHA2_TO_ALPHA3 = {
    "AD": "AND", "AE": "ARE", "AF": "AFG", "AG": "ATG", "AI": "AIA",
    "AL": "ALB", "AM": "ARM", "AO": "AGO", "AQ": "ATA", "AR": "ARG",
    "AS": "ASM", "AT": "AUT", "AU": "AUS", "AW": "ABW", "AZ": "AZE",
    "BA": "BIH", "BB": "BRB", "BD": "BGD", "BE": "BEL", "BF": "BFA",
    "BG": "BGR", "BH": "BHR", "BI": "BDI", "BJ": "BEN", "BL": "BLM",
    "BM": "BMU", "BN": "BRN", "BO": "BOL", "BQ": "BES", "BR": "BRA", "BS": "BHS",
    "BT": "BTN", "BW": "BWA", "BY": "BLR", "BZ": "BLZ", "CA": "CAN",
    "CC": "CCK", "CD": "COD", "CF": "CAF", "CG": "COG", "CH": "CHE",
    "CI": "CIV", "CK": "COK", "CL": "CHL", "CM": "CMR", "CN": "CHN",
    "CO": "COL", "CR": "CRI", "CU": "CUB", "CV": "CPV", "CW": "CUW",
    "CX": "CXR", "CY": "CYP", "CZ": "CZE", "DE": "DEU", "DJ": "DJI",
    "DK": "DNK", "DM": "DMA", "DO": "DOM", "DZ": "DZA", "EC": "ECU",
    "EE": "EST", "EG": "EGY", "EH": "ESH", "ER": "ERI", "ES": "ESP",
    "ET": "ETH", "FI": "FIN", "FJ": "FJI", "FK": "FLK", "FM": "FSM",
    "FO": "FRO", "FR": "FRA", "GA": "GAB", "GB": "GBR", "GD": "GRD",
    "GE": "GEO", "GF": "GUF", "GG": "GGY", "GH": "GHA", "GI": "GIB",
    "GL": "GRL", "GM": "GMB", "GN": "GIN", "GP": "GLP", "GQ": "GNQ",
    "GR": "GRC", "GT": "GTM", "GU": "GUM", "GW": "GNB", "GY": "GUY",
    "HK": "HKG", "HN": "HND", "HR": "HRV", "HT": "HTI", "HU": "HUN",
    "ID": "IDN", "IE": "IRL", "IL": "ISR", "IM": "IMN", "IN": "IND",
    "IO": "IOT", "IQ": "IRQ", "IR": "IRN", "IS": "ISL", "IT": "ITA",
    "JE": "JEY", "JM": "JAM", "JO": "JOR", "JP": "JPN", "KE": "KEN",
    "KG": "KGZ", "KH": "KHM", "KI": "KIR", "KM": "COM", "KN": "KNA",
    "KP": "PRK", "KR": "KOR", "KW": "KWT", "KY": "CYM", "KZ": "KAZ",
    "LA": "LAO", "LB": "LBN", "LC": "LCA", "LI": "LIE", "LK": "LKA",
    "LR": "LBR", "LS": "LSO", "LT": "LTU", "LU": "LUX", "LV": "LVA",
    "LY": "LBY", "MA": "MAR", "MC": "MCO", "MD": "MDA", "ME": "MNE",
    "MF": "MAF", "MG": "MDG", "MH": "MHL", "MK": "MKD", "ML": "MLI",
    "MM": "MMR", "MN": "MNG", "MO": "MAC", "MP": "MNP", "MQ": "MTQ",
    "MR": "MRT", "MS": "MSR", "MT": "MLT", "MU": "MUS", "MV": "MDV",
    "MW": "MWI", "MX": "MEX", "MY": "MYS", "MZ": "MOZ", "NA": "NAM",
    "NC": "NCL", "NE": "NER", "NF": "NFK", "NG": "NGA", "NI": "NIC",
    "NL": "NLD", "NO": "NOR", "NP": "NPL", "NR": "NRU", "NU": "NIU",
    "NZ": "NZL", "OM": "OMN", "PA": "PAN", "PE": "PER", "PF": "PYF",
    "PG": "PNG", "PH": "PHL", "PK": "PAK", "PL": "POL", "PM": "SPM",
    "PN": "PCN", "PR": "PRI", "PS": "PSE", "PT": "PRT", "PW": "PLW",
    "PY": "PRY", "QA": "QAT", "RE": "REU", "RO": "ROU", "RS": "SRB",
    "RU": "RUS", "RW": "RWA", "SA": "SAU", "SB": "SLB", "SC": "SYC",
    "SD": "SDN", "SE": "SWE", "SG": "SGP", "SH": "SHN", "SI": "SVN",
    "SJ": "SJM", "SK": "SVK", "SL": "SLE", "SM": "SMR", "SN": "SEN",
    "SO": "SOM", "SR": "SUR", "SS": "SSD", "ST": "STP", "SV": "SLV",
    "SX": "SXM", "SY": "SYR", "SZ": "SWZ", "TC": "TCA", "TD": "TCD",
    "TF": "ATF", "TG": "TGO", "TH": "THA", "TJ": "TJK", "TK": "TKL",
    "TL": "TLS", "TM": "TKM", "TN": "TUN", "TO": "TON", "TR": "TUR",
    "TT": "TTO", "TV": "TUV", "TW": "TWN", "TZ": "TZA", "UA": "UKR",
    "UG": "UGA", "US": "USA", "UY": "URY", "UZ": "UZB", "VA": "VAT",
    "VC": "VCT", "VE": "VEN", "VG": "VGB", "VI": "VIR", "VN": "VNM",
    "VU": "VUT", "WF": "WLF", "WS": "WSM", "XK": "SRB", "YE": "YEM",
    "YT": "MYT", "ZA": "ZAF", "ZM": "ZMB", "ZW": "ZWE",
}


def log(msg):
    print(msg, flush=True)
    with open(TASK_LOG, "a") as f:
        f.write(msg + "\n")


def main():
    log("[Extract] Starting reverse geocoding of nationalities...")

    # Load modern_country table for name lookup by iso_a3
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT name, iso_a3_code FROM modern_country")
    iso3_to_name = {}
    for name, iso3 in c.fetchall():
        iso3_to_name[iso3] = name

    # Get nationalities with lat/lon
    c.execute(
        "SELECT wikidata_id, name_en, lat, lon FROM nationalities WHERE lat IS NOT NULL AND lon IS NOT NULL"
    )
    nationalities = c.fetchall()
    log(f"[Extract] Found {len(nationalities)} nationalities with lat/lon")

    # Also get nationalities without lat/lon
    c.execute(
        "SELECT wikidata_id, name_en FROM nationalities WHERE lat IS NULL OR lon IS NULL"
    )
    no_coords = c.fetchall()
    log(f"[Extract] Found {len(no_coords)} nationalities without lat/lon")
    conn.close()

    # Prepare coordinates for batch reverse geocoding
    coords = [(row[2], row[3]) for row in nationalities]

    log("[Extract] Running reverse geocoder (batch)...")
    results = rg.search(coords)
    log(f"[Extract] Reverse geocoding complete for {len(results)} points")

    # Build the output mapping
    output = {}
    errors = []
    mapped = 0

    for i, (wikidata_id, name_en, lat, lon) in enumerate(nationalities):
        cc2 = results[i]["cc"]
        cc3 = ALPHA2_TO_ALPHA3.get(cc2)

        if cc3 and cc3 in iso3_to_name:
            country_name = iso3_to_name[cc3]
            output[wikidata_id] = {
                "country_name": country_name,
                "iso_a3_code": cc3,
                "geocoder_cc": cc2,
                "geocoder_name": results[i]["name"],
            }
            mapped += 1
        else:
            errors.append(
                {
                    "wikidata_id": wikidata_id,
                    "name_en": name_en,
                    "lat": lat,
                    "lon": lon,
                    "cc2": cc2,
                    "cc3": cc3,
                }
            )

        if (i + 1) % 500 == 0:
            log(f"[Extract] Processed {i+1}/{len(nationalities)} nationalities")

    log(f"[Extract] Mapped {mapped}/{len(nationalities)} nationalities to modern countries")
    log(f"[Extract] {len(errors)} errors/unmapped")

    if errors:
        log("[Extract] Unmapped nationalities:")
        for e in errors:
            log(f"  {e['wikidata_id']} ({e['name_en']}): cc2={e['cc2']}, cc3={e['cc3']}")

    # Save output
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    log(f"[Extract] Saved results to {OUTPUT_PATH}")

    # Save errors for retry
    if errors:
        error_path = OUTPUT_PATH.replace(".json", "_errors.json")
        with open(error_path, "w") as f:
            json.dump(errors, f, ensure_ascii=False, indent=2)
        log(f"[Extract] Saved errors to {error_path}")

    log("[Extract] Done.")


if __name__ == "__main__":
    main()
