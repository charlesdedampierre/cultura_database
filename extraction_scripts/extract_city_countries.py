"""
Reverse geocode cities lat/lon to find modern countries.
Saves results as JSON in data/all_humans/city_modern_countries.json
"""

import sqlite3
import json
import os
import subprocess

try:
    subprocess.Popen(["caffeinate"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except FileNotFoundError:
    pass

import reverse_geocoder as rg

DB_PATH = "data/humans_clean.sqlite3"
OUTPUT_PATH = "data/all_humans/city_modern_countries.json"
TASK_LOG = "task.log"

ALPHA2_TO_ALPHA3 = {
    "AD": "AND", "AE": "ARE", "AF": "AFG", "AG": "ATG", "AI": "AIA", "AX": "FIN",
    "AL": "ALB", "AM": "ARM", "AO": "AGO", "AQ": "ATA", "AR": "ARG",
    "AS": "ASM", "AT": "AUT", "AU": "AUS", "AW": "ABW", "AZ": "AZE",
    "BA": "BIH", "BB": "BRB", "BD": "BGD", "BE": "BEL", "BF": "BFA",
    "BG": "BGR", "BH": "BHR", "BI": "BDI", "BJ": "BEN", "BL": "BLM",
    "BM": "BMU", "BN": "BRN", "BO": "BOL", "BQ": "BES", "BR": "BRA",
    "BS": "BHS", "BT": "BTN", "BW": "BWA", "BY": "BLR", "BZ": "BLZ",
    "CA": "CAN", "CC": "CCK", "CD": "COD", "CF": "CAF", "CG": "COG",
    "CH": "CHE", "CI": "CIV", "CK": "COK", "CL": "CHL", "CM": "CMR",
    "CN": "CHN", "CO": "COL", "CR": "CRI", "CU": "CUB", "CV": "CPV",
    "CW": "CUW", "CX": "CXR", "CY": "CYP", "CZ": "CZE", "DE": "DEU",
    "DJ": "DJI", "DK": "DNK", "DM": "DMA", "DO": "DOM", "DZ": "DZA",
    "EC": "ECU", "EE": "EST", "EG": "EGY", "EH": "ESH", "ER": "ERI",
    "ES": "ESP", "ET": "ETH", "FI": "FIN", "FJ": "FJI", "FK": "FLK",
    "FM": "FSM", "FO": "FRO", "FR": "FRA", "GA": "GAB", "GB": "GBR",
    "GD": "GRD", "GE": "GEO", "GF": "GUF", "GG": "GGY", "GH": "GHA",
    "GI": "GIB", "GL": "GRL", "GM": "GMB", "GN": "GIN", "GP": "GLP",
    "GQ": "GNQ", "GR": "GRC", "GS": "SGS", "GT": "GTM", "GU": "GUM", "GW": "GNB",
    "GY": "GUY", "HK": "HKG", "HN": "HND", "HR": "HRV", "HT": "HTI",
    "HU": "HUN", "ID": "IDN", "IE": "IRL", "IL": "ISR", "IM": "IMN",
    "IN": "IND", "IO": "IOT", "IQ": "IRQ", "IR": "IRN", "IS": "ISL",
    "IT": "ITA", "JE": "GBR", "JM": "JAM", "JO": "JOR", "JP": "JPN",
    "KE": "KEN", "KG": "KGZ", "KH": "KHM", "KI": "KIR", "KM": "COM",
    "KN": "KNA", "KP": "PRK", "KR": "KOR", "KW": "KWT", "KY": "CYM",
    "KZ": "KAZ", "LA": "LAO", "LB": "LBN", "LC": "LCA", "LI": "LIE",
    "LK": "LKA", "LR": "LBR", "LS": "LSO", "LT": "LTU", "LU": "LUX",
    "LV": "LVA", "LY": "LBY", "MA": "MAR", "MC": "MCO", "MD": "MDA",
    "ME": "MNE", "MF": "MAF", "MG": "MDG", "MH": "MHL", "MK": "MKD",
    "ML": "MLI", "MM": "MMR", "MN": "MNG", "MO": "MAC", "MP": "MNP",
    "MQ": "MTQ", "MR": "MRT", "MS": "MSR", "MT": "MLT", "MU": "MUS",
    "MV": "MDV", "MW": "MWI", "MX": "MEX", "MY": "MYS", "MZ": "MOZ",
    "NA": "NAM", "NC": "NCL", "NE": "NER", "NF": "NFK", "NG": "NGA",
    "NI": "NIC", "NL": "NLD", "NO": "NOR", "NP": "NPL", "NR": "NRU",
    "NU": "NIU", "NZ": "NZL", "OM": "OMN", "PA": "PAN", "PE": "PER",
    "PF": "PYF", "PG": "PNG", "PH": "PHL", "PK": "PAK", "PL": "POL",
    "PM": "SPM", "PN": "PCN", "PR": "PRI", "PS": "PSE", "PT": "PRT",
    "PW": "PLW", "PY": "PRY", "QA": "QAT", "RE": "REU", "RO": "ROU",
    "RS": "SRB", "RU": "RUS", "RW": "RWA", "SA": "SAU", "SB": "SLB",
    "SC": "SYC", "SD": "SDN", "SE": "SWE", "SG": "SGP", "SH": "SHN",
    "SI": "SVN", "SJ": "SJM", "SK": "SVK", "SL": "SLE", "SM": "SMR",
    "SN": "SEN", "SO": "SOM", "SR": "SUR", "SS": "SSD", "ST": "STP",
    "SV": "SLV", "SX": "SXM", "SY": "SYR", "SZ": "SWZ", "TC": "TCA",
    "TD": "TCD", "TF": "ATF", "TG": "TGO", "TH": "THA", "TJ": "TJK",
    "TK": "TKL", "TL": "TLS", "TM": "TKM", "TN": "TUN", "TO": "TON",
    "TR": "TUR", "TT": "TTO", "TV": "TUV", "TW": "TWN", "TZ": "TZA",
    "UA": "UKR", "UG": "UGA", "US": "USA", "UY": "URY", "UZ": "UZB",
    "VA": "VAT", "VC": "VCT", "VE": "VEN", "VG": "VGB", "VI": "VIR",
    "VN": "VNM", "VU": "VUT", "WF": "WLF", "WS": "WSM", "XK": "SRB",
    "YE": "YEM", "YT": "MYT", "ZA": "ZAF", "ZM": "ZMB", "ZW": "ZWE",
}


def log(msg):
    print(msg, flush=True)
    with open(TASK_LOG, "a") as f:
        f.write(msg + "\n")


def main():
    log("[Extract] Starting reverse geocoding of cities...")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Load modern_country for name lookup
    c.execute("SELECT name, iso_a3_code FROM modern_country")
    iso3_to_name = {}
    for name, iso3 in c.fetchall():
        iso3_to_name[iso3] = name

    # Get all cities
    c.execute("SELECT id, name_en, lat, lon FROM cities WHERE lat IS NOT NULL AND lon IS NOT NULL")
    cities = c.fetchall()
    log(f"[Extract] Found {len(cities)} cities with lat/lon")
    conn.close()

    # Batch reverse geocode
    coords = [(row[2], row[3]) for row in cities]

    log("[Extract] Running reverse geocoder (batch for all cities)...")
    results = rg.search(coords)
    log(f"[Extract] Reverse geocoding complete for {len(results)} points")

    # Build output
    output = {}
    errors = []
    mapped = 0

    for i, (city_id, name_en, lat, lon) in enumerate(cities):
        cc2 = results[i]["cc"]
        cc3 = ALPHA2_TO_ALPHA3.get(cc2)

        if cc3 and cc3 in iso3_to_name:
            country_name = iso3_to_name[cc3]
            output[city_id] = {
                "country_name": country_name,
                "iso_a3_code": cc3,
            }
            mapped += 1
        else:
            errors.append({
                "city_id": city_id,
                "name_en": name_en,
                "lat": lat,
                "lon": lon,
                "cc2": cc2,
                "cc3": cc3,
            })

        if (i + 1) % 50000 == 0:
            log(f"[Extract] Processed {i+1}/{len(cities)} cities")

    log(f"[Extract] Mapped {mapped}/{len(cities)} cities to modern countries")
    log(f"[Extract] {len(errors)} errors/unmapped")

    if errors:
        log("[Extract] Unmapped cities (sample):")
        for e in errors[:20]:
            log(f"  {e['city_id']} ({e['name_en']}): cc2={e['cc2']}, cc3={e['cc3']}")

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, ensure_ascii=False)
    log(f"[Extract] Saved results to {OUTPUT_PATH}")

    if errors:
        error_path = OUTPUT_PATH.replace(".json", "_errors.json")
        with open(error_path, "w") as f:
            json.dump(errors, f, ensure_ascii=False, indent=2)
        log(f"[Extract] Saved errors to {error_path}")

    log("[Extract] Done.")


if __name__ == "__main__":
    main()
