"""
For nationalities without iso_country_name, query QLEVER to find their parent/containing
modern country via P17 (country), P131 (located in), P361 (part of), P276 (location).
Save results as JSON.
"""

import json
import sqlite3
import requests
import subprocess
import time

try:
    subprocess.Popen(["caffeinate"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except FileNotFoundError:
    pass

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"
DB_PATH = "data/humans_clean.sqlite3"
OUTPUT_PATH = "data/all_humans/nationality_parent_countries.json"
TASK_LOG = "task.log"


def log(msg):
    print(msg, flush=True)
    with open(TASK_LOG, "a") as f:
        f.write(msg + "\n")


def extract_qid(uri):
    if "/Q" in uri:
        return uri.split("/")[-1].rstrip(">")
    return uri


def fetch_country_relations(qids):
    """Fetch P17 (country), P131 (located in), P361 (part of) for a batch of QIDs."""
    values = " ".join([f"wd:{qid}" for qid in qids])
    query = f"""
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?entity ?country ?countryLabel WHERE {{
  VALUES ?entity {{ {values} }}
  {{
    ?entity wdt:P17 ?country .
  }} UNION {{
    ?entity wdt:P131 ?country .
  }} UNION {{
    ?entity wdt:P361 ?country .
  }} UNION {{
    ?entity wdt:P276 ?country .
  }}
  ?country rdfs:label ?countryLabel .
  FILTER(LANG(?countryLabel) = "en")
}}
"""
    data = {"query": query, "action": "tsv_export"}
    response = requests.post(QLEVER_ENDPOINT, data=data, timeout=120)
    response.raise_for_status()

    results = {}
    lines = response.text.strip().split("\n")
    for line in lines[1:]:
        if line:
            parts = line.strip().split("\t")
            if len(parts) >= 3:
                entity_qid = extract_qid(parts[0])
                country_qid = extract_qid(parts[1])
                country_label = parts[2].strip('"').split('"')[0]
                if entity_qid not in results:
                    results[entity_qid] = []
                results[entity_qid].append({
                    "country_id": country_qid,
                    "country_name": country_label,
                })
    return results


def fetch_location_coords(qids):
    """Fetch P625 (coordinate location) for entities - as backup for reverse geocoding."""
    values = " ".join([f"wd:{qid}" for qid in qids])
    query = f"""
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?entity ?coord WHERE {{
  VALUES ?entity {{ {values} }}
  ?entity wdt:P625 ?coord .
}}
"""
    data = {"query": query, "action": "tsv_export"}
    response = requests.post(QLEVER_ENDPOINT, data=data, timeout=120)
    response.raise_for_status()

    results = {}
    lines = response.text.strip().split("\n")
    for line in lines[1:]:
        if line:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                entity_qid = extract_qid(parts[0])
                coord = parts[1]
                # Parse "Point(lon lat)" format
                if "Point(" in coord:
                    coord = coord.replace('"', '').strip()
                    inner = coord.split("Point(")[1].rstrip(")")
                    lon_str, lat_str = inner.split()
                    try:
                        results[entity_qid] = {
                            "lat": float(lat_str),
                            "lon": float(lon_str),
                        }
                    except ValueError:
                        pass
    return results


def main():
    log("[Extract] Finding parent countries for unmapped nationalities...")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Load modern countries
    c.execute("SELECT name, iso_a3_code, id FROM modern_country")
    modern_by_name = {}
    modern_by_id = {}
    for name, iso3, wid in c.fetchall():
        modern_by_name[name] = {"iso_a3_code": iso3, "id": wid}
        modern_by_id[wid] = {"name": name, "iso_a3_code": iso3}

    # Get unmapped nationalities
    c.execute(
        "SELECT wikidata_id, name_en, count FROM nationalities WHERE iso_country_name IS NULL"
    )
    unmapped = [(r[0], r[1], r[2]) for r in c.fetchall()]
    conn.close()

    log(f"[Extract] {len(unmapped)} unmapped nationalities, {len(modern_by_name)} modern countries")

    # Step 1: Query QLEVER for country/part-of relations
    all_relations = {}
    errors = []
    batch_size = 100
    qids = [u[0] for u in unmapped]

    log("[Extract] Querying QLEVER for country relations (P17/P131/P361/P276)...")
    for i in range(0, len(qids), batch_size):
        batch = qids[i : i + batch_size]
        try:
            results = fetch_country_relations(batch)
            all_relations.update(results)
            log(
                f"[Extract] Batch {i//batch_size + 1}/{(len(qids) + batch_size - 1)//batch_size}: found relations for {len(results)} entities"
            )
        except Exception as e:
            errors.append({"batch_start": i, "ids": batch, "error": str(e)})
            log(f"[Extract] Error in batch {i}: {e}")
        time.sleep(0.3)

    # Retry errors
    if errors:
        log(f"[Extract] Retrying {len(errors)} failed batches...")
        for err in errors:
            try:
                results = fetch_country_relations(err["ids"])
                all_relations.update(results)
            except Exception as e:
                log(f"[Extract] Retry failed: {e}")
            time.sleep(0.5)

    log(f"[Extract] Found relations for {len(all_relations)} nationalities")

    # Step 2: For those without relations, try to get coordinates
    no_relation_qids = [q for q in qids if q not in all_relations]
    log(f"[Extract] {len(no_relation_qids)} nationalities without relations, trying coordinates...")

    all_coords = {}
    if no_relation_qids:
        for i in range(0, len(no_relation_qids), batch_size):
            batch = no_relation_qids[i : i + batch_size]
            try:
                results = fetch_location_coords(batch)
                all_coords.update(results)
            except Exception as e:
                log(f"[Extract] Coord error: {e}")
            time.sleep(0.3)
        log(f"[Extract] Found coordinates for {len(all_coords)} entities")

    # Step 3: Reverse geocode the coordinates
    mapped_from_coords = {}
    if all_coords:
        import reverse_geocoder as rg

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
            "GQ": "GNQ", "GR": "GRC", "GS": "SGS", "GT": "GTM", "GU": "GUM",
            "GW": "GNB", "GY": "GUY", "HK": "HKG", "HN": "HND", "HR": "HRV",
            "HT": "HTI", "HU": "HUN", "ID": "IDN", "IE": "IRL", "IL": "ISR",
            "IM": "IMN", "IN": "IND", "IO": "IOT", "IQ": "IRQ", "IR": "IRN",
            "IS": "ISL", "IT": "ITA", "JE": "GBR", "JM": "JAM", "JO": "JOR",
            "JP": "JPN", "KE": "KEN", "KG": "KGZ", "KH": "KHM", "KI": "KIR",
            "KM": "COM", "KN": "KNA", "KP": "PRK", "KR": "KOR", "KW": "KWT",
            "KY": "CYM", "KZ": "KAZ", "LA": "LAO", "LB": "LBN", "LC": "LCA",
            "LI": "LIE", "LK": "LKA", "LR": "LBR", "LS": "LSO", "LT": "LTU",
            "LU": "LUX", "LV": "LVA", "LY": "LBY", "MA": "MAR", "MC": "MCO",
            "MD": "MDA", "ME": "MNE", "MF": "MAF", "MG": "MDG", "MH": "MHL",
            "MK": "MKD", "ML": "MLI", "MM": "MMR", "MN": "MNG", "MO": "MAC",
            "MP": "MNP", "MQ": "MTQ", "MR": "MRT", "MS": "MSR", "MT": "MLT",
            "MU": "MUS", "MV": "MDV", "MW": "MWI", "MX": "MEX", "MY": "MYS",
            "MZ": "MOZ", "NA": "NAM", "NC": "NCL", "NE": "NER", "NF": "NFK",
            "NG": "NGA", "NI": "NIC", "NL": "NLD", "NO": "NOR", "NP": "NPL",
            "NR": "NRU", "NU": "NIU", "NZ": "NZL", "OM": "OMN", "PA": "PAN",
            "PE": "PER", "PF": "PYF", "PG": "PNG", "PH": "PHL", "PK": "PAK",
            "PL": "POL", "PM": "SPM", "PN": "PCN", "PR": "PRI", "PS": "PSE",
            "PT": "PRT", "PW": "PLW", "PY": "PRY", "QA": "QAT", "RE": "REU",
            "RO": "ROU", "RS": "SRB", "RU": "RUS", "RW": "RWA", "SA": "SAU",
            "SB": "SLB", "SC": "SYC", "SD": "SDN", "SE": "SWE", "SG": "SGP",
            "SH": "SHN", "SI": "SVN", "SJ": "SJM", "SK": "SVK", "SL": "SLE",
            "SM": "SMR", "SN": "SEN", "SO": "SOM", "SR": "SUR", "SS": "SSD",
            "ST": "STP", "SV": "SLV", "SX": "SXM", "SY": "SYR", "SZ": "SWZ",
            "TC": "TCA", "TD": "TCD", "TF": "ATF", "TG": "TGO", "TH": "THA",
            "TJ": "TJK", "TK": "TKL", "TL": "TLS", "TM": "TKM", "TN": "TUN",
            "TO": "TON", "TR": "TUR", "TT": "TTO", "TV": "TUV", "TW": "TWN",
            "TZ": "TZA", "UA": "UKR", "UG": "UGA", "US": "USA", "UY": "URY",
            "UZ": "UZB", "VA": "VAT", "VC": "VCT", "VE": "VEN", "VG": "VGB",
            "VI": "VIR", "VN": "VNM", "VU": "VUT", "WF": "WLF", "WS": "WSM",
            "XK": "SRB", "YE": "YEM", "YT": "MYT", "ZA": "ZAF", "ZM": "ZMB",
            "ZW": "ZWE",
        }

        coord_list = list(all_coords.items())
        coords = [(v["lat"], v["lon"]) for _, v in coord_list]
        geo_results = rg.search(coords)

        for idx, (qid, _) in enumerate(coord_list):
            cc2 = geo_results[idx]["cc"]
            cc3 = ALPHA2_TO_ALPHA3.get(cc2)
            if cc3 and cc3 in modern_by_id:
                info = modern_by_id[cc3]
                # Skip if lat/lon is 0,0
                if all_coords[qid]["lat"] == 0.0 and all_coords[qid]["lon"] == 0.0:
                    continue
                mapped_from_coords[qid] = {
                    "country_name": info["name"],
                    "iso_a3_code": cc3,
                    "source": "coordinates",
                }

        log(f"[Extract] Mapped {len(mapped_from_coords)} from coordinates")

    # Step 4: Match relations to modern countries
    output = {}

    for qid, name, count in unmapped:
        # Try from coords first (most reliable)
        if qid in mapped_from_coords:
            output[qid] = mapped_from_coords[qid]
            continue

        # Try from relations
        if qid in all_relations:
            relations = all_relations[qid]
            # Check if any related entity is a modern country (by name match)
            for rel in relations:
                cn = rel["country_name"]
                if cn in modern_by_name:
                    output[qid] = {
                        "country_name": cn,
                        "iso_a3_code": modern_by_name[cn]["iso_a3_code"],
                        "source": "relation",
                        "via_id": rel["country_id"],
                    }
                    break

            # If not directly found, check if the related entity's ID matches
            if qid not in output:
                for rel in relations:
                    cid = rel["country_id"]
                    if cid in modern_by_id:
                        output[qid] = {
                            "country_name": modern_by_id[cid]["name"],
                            "iso_a3_code": modern_by_id[cid]["iso_a3_code"],
                            "source": "relation_id",
                            "via_id": cid,
                        }
                        break

    log(f"[Extract] Total mapped: {len(output)} / {len(unmapped)}")
    log(f"[Extract] Still unmapped: {len(unmapped) - len(output)}")

    # Show what we found
    name_lookup = {u[0]: (u[1], u[2]) for u in unmapped}
    mapped_count_sum = sum(name_lookup[qid][1] for qid in output if qid in name_lookup)
    log(f"[Extract] Individual references covered by new mappings: {mapped_count_sum}")

    # Show top mapped
    mapped_sorted = sorted(output.items(), key=lambda x: name_lookup.get(x[0], ("", 0))[1], reverse=True)
    log("[Extract] Top mapped nationalities:")
    for qid, info in mapped_sorted[:20]:
        name, cnt = name_lookup.get(qid, ("?", 0))
        log(f"  {qid} ({name}, count={cnt}) -> {info['country_name']} ({info['iso_a3_code']}) via {info['source']}")

    # Show remaining unmapped
    still_unmapped = [(qid, name, cnt) for qid, name, cnt in unmapped if qid not in output]
    still_unmapped.sort(key=lambda x: x[2], reverse=True)
    log(f"\n[Extract] Top still-unmapped nationalities:")
    for qid, name, cnt in still_unmapped[:20]:
        rels = all_relations.get(qid, [])
        rel_str = "; ".join([f"{r['country_name']}({r['country_id']})" for r in rels[:3]])
        log(f"  {qid} ({name}, count={cnt}) relations=[{rel_str}]")

    # Save
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    log(f"[Extract] Saved to {OUTPUT_PATH}")

    log("[Extract] Done.")


if __name__ == "__main__":
    main()
