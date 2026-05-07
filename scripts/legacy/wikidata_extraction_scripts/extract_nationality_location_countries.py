"""
For nationalities without iso_country_name, query QLEVER to find modern country mapping.

Strategy:
1. P17/P131/P1366 direct match to modern_country table
2. P1366 chain: if replaced-by entity is an already-mapped nationality, use its country
3. P36 (capital) -> P625 (coords) -> reverse geocode to find country
4. Deep chain following (P17/P1366 up to 3 levels)
5. Capital city -> P17 (country of capital)

Only maps to countries that exist in the modern_country table.
Saves results as JSON in data/all_humans/nationality_location_countries.json
"""

import json
import sqlite3
import requests
import subprocess
import time
import os

try:
    subprocess.Popen(["caffeinate"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except FileNotFoundError:
    pass

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"
DB_PATH = "data/humans_clean.sqlite3"
OUTPUT_PATH = "data/all_humans/nationality_location_countries.json"
ERRORS_PATH = "data/all_humans/nationality_location_countries_errors.json"
TASK_LOG = "task.log"
BATCH_SIZE = 80


def log(msg):
    print(msg, flush=True)
    with open(TASK_LOG, "a") as f:
        f.write(msg + "\n")


def extract_qid(uri):
    if not uri:
        return uri
    if "/Q" in uri:
        return uri.split("/")[-1].rstrip(">")
    if uri.startswith("Q"):
        return uri
    return uri


def qlever_query(query, retries=2):
    for attempt in range(retries + 1):
        try:
            data = {"query": query, "action": "tsv_export"}
            response = requests.post(QLEVER_ENDPOINT, data=data, timeout=120)
            response.raise_for_status()
            return response.text
        except Exception as e:
            if attempt < retries:
                wait = 2 * (attempt + 1)
                log(f"  Query error (attempt {attempt + 1}): {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


def parse_tsv(text, expected_cols):
    lines = text.strip().split("\n")
    results = []
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.strip().split("\t")
        if len(parts) >= expected_cols:
            results.append(tuple(parts[:expected_cols]))
    return results


def fetch_relations(qids):
    """Fetch P17, P131, P1366 for a batch."""
    values = " ".join([f"wd:{qid}" for qid in qids])
    query = f"""
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?entity ?rel ?target ?targetLabel WHERE {{
  VALUES ?entity {{ {values} }}
  {{
    ?entity wdt:P17 ?target . BIND("P17" AS ?rel)
  }} UNION {{
    ?entity wdt:P131 ?target . BIND("P131" AS ?rel)
  }} UNION {{
    ?entity wdt:P1366 ?target . BIND("P1366" AS ?rel)
  }}
  ?target rdfs:label ?targetLabel .
  FILTER(LANG(?targetLabel) = "en")
}}
"""
    text = qlever_query(query)
    rows = parse_tsv(text, 4)
    results = {}
    for row in rows:
        entity_qid = extract_qid(row[0])
        rel = row[1].strip('"')
        target_qid = extract_qid(row[2])
        target_label = row[3].strip('"').split('"')[0]
        if entity_qid not in results:
            results[entity_qid] = []
        results[entity_qid].append({
            "target_id": target_qid,
            "target_name": target_label,
            "relation": rel,
        })
    return results


def fetch_capital_coords(qids):
    """Fetch P36 (capital) -> P625 (coordinates of capital)."""
    values = " ".join([f"wd:{qid}" for qid in qids])
    # Use Wikidata SPARQL for coordinates since QLEVER returns blank nodes
    query = f"""
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?entity ?capital ?capitalLabel ?coord WHERE {{
  VALUES ?entity {{ {values} }}
  ?entity wdt:P36 ?capital .
  ?capital wdt:P625 ?coord .
  ?capital rdfs:label ?capitalLabel . FILTER(LANG(?capitalLabel) = "en")
}}
"""
    headers = {'Accept': 'text/tab-separated-values', 'User-Agent': 'CulturaDB/1.0'}
    params = {'query': query}
    response = requests.get('https://query.wikidata.org/sparql', params=params, headers=headers, timeout=120)
    response.raise_for_status()

    results = {}
    lines = response.text.strip().split("\n")
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.strip().split("\t")
        if len(parts) >= 4:
            entity_qid = extract_qid(parts[0].strip("<>"))
            capital_label = parts[2].strip('"').split('"')[0]
            coord = parts[3]
            if "Point(" in coord:
                coord = coord.replace('"', '').replace('^^<http://www.opengis.net/ont/geosparql#wktLiteral>', '').strip()
                inner = coord.split("Point(")[1].rstrip(")")
                try:
                    lon_str, lat_str = inner.split()
                    lat, lon = float(lat_str), float(lon_str)
                    if not (lat == 0.0 and lon == 0.0):
                        results[entity_qid] = {
                            "lat": lat, "lon": lon,
                            "capital": capital_label,
                        }
                except (ValueError, IndexError):
                    pass
    return results


def fetch_capital_country(qids):
    """Fetch P36 (capital) -> P17 (country of capital) via QLEVER."""
    values = " ".join([f"wd:{qid}" for qid in qids])
    query = f"""
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?entity ?country ?countryLabel WHERE {{
  VALUES ?entity {{ {values} }}
  ?entity wdt:P36 ?capital .
  ?capital wdt:P17 ?country .
  ?country rdfs:label ?countryLabel . FILTER(LANG(?countryLabel) = "en")
}}
"""
    text = qlever_query(query)
    rows = parse_tsv(text, 3)
    results = {}
    for row in rows:
        entity_qid = extract_qid(row[0])
        country_qid = extract_qid(row[1])
        country_label = row[2].strip('"').split('"')[0]
        if entity_qid not in results:
            results[entity_qid] = []
        results[entity_qid].append({
            "country_id": country_qid,
            "country_name": country_label,
        })
    return results


def batch_query(func, qids, label=""):
    all_results = {}
    errors = []
    total_batches = (len(qids) + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, len(qids), BATCH_SIZE):
        batch = qids[i: i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        try:
            results = func(batch)
            all_results.update(results)
            log(f"  [{label}] Batch {batch_num}/{total_batches}: {len(results)} results")
        except Exception as e:
            errors.append({"batch_start": i, "ids": batch, "error": str(e)})
            log(f"  [{label}] Batch {batch_num} ERROR: {e}")
        time.sleep(0.5)

    if errors:
        log(f"  [{label}] Retrying {len(errors)} failed batches...")
        retry_errors = []
        for err in errors:
            try:
                time.sleep(2)
                results = func(err["ids"])
                all_results.update(results)
                log(f"  [{label}] Retry success: {len(results)} results")
            except Exception as e:
                retry_errors.append(err)
                log(f"  [{label}] Retry failed: {e}")
        errors = retry_errors

    return all_results, errors


def main():
    log("[Extract-Loc] === Starting nationality location country extraction ===")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Load modern countries
    c.execute("SELECT id, name, iso_a3_code FROM modern_country")
    modern_by_name = {}
    modern_by_id = {}
    modern_names_lower = {}
    iso3_to_name = {}
    for wid, name, iso3 in c.fetchall():
        modern_by_name[name] = {"iso_a3_code": iso3, "id": wid}
        modern_by_id[wid] = {"name": name, "iso_a3_code": iso3}
        modern_names_lower[name.lower()] = {"name": name, "iso_a3_code": iso3, "id": wid}
        iso3_to_name[iso3] = name

    # Load already-mapped nationalities (to use as bridge)
    c.execute("SELECT wikidata_id, iso_country_name, iso_a3_code FROM nationalities WHERE iso_country_name IS NOT NULL")
    mapped_nats = {}
    for wid, cn, iso in c.fetchall():
        mapped_nats[wid] = {"country_name": cn, "iso_a3_code": iso}

    # Get unmapped nationalities
    c.execute(
        "SELECT wikidata_id, name_en, count FROM nationalities WHERE iso_country_name IS NULL ORDER BY count DESC"
    )
    unmapped = [(r[0], r[1], r[2]) for r in c.fetchall()]
    conn.close()

    log(f"[Extract-Loc] {len(unmapped)} unmapped, {len(modern_by_name)} modern countries, {len(mapped_nats)} already-mapped nats")

    qids = [u[0] for u in unmapped]
    name_lookup = {u[0]: (u[1], u[2]) for u in unmapped}

    # ========================================
    # Step 1: Get P17/P131/P1366 (level 1)
    # ========================================
    log("[Extract-Loc] Step 1: Querying P17/P131/P1366 (level 1)...")
    level1_relations, level1_errors = batch_query(fetch_relations, qids, "L1")
    log(f"[Extract-Loc] Found level-1 relations for {len(level1_relations)} entities")

    # ========================================
    # Step 2: Level 2 for non-modern targets
    # ========================================
    level1_targets = set()
    for qid, rels in level1_relations.items():
        for r in rels:
            tid = r["target_id"]
            if tid not in modern_by_id and tid not in mapped_nats and tid != qid:
                level1_targets.add(tid)

    level1_targets = list(level1_targets)
    log(f"[Extract-Loc] Step 2: Querying {len(level1_targets)} level-1 targets (level 2)...")
    level2_relations = {}
    if level1_targets:
        level2_relations, _ = batch_query(fetch_relations, level1_targets, "L2")
    log(f"[Extract-Loc] Found level-2 relations for {len(level2_relations)} entities")

    # ========================================
    # Step 3: Capital city coordinates (Wikidata SPARQL) for reverse geocoding
    # ========================================
    log("[Extract-Loc] Step 3: Querying capital city coordinates (Wikidata SPARQL)...")
    # Use smaller batches for Wikidata SPARQL to avoid timeouts
    old_batch = BATCH_SIZE
    capital_coords = {}
    cap_coord_errors = []
    wikidata_batch = 30
    total_wikidata_batches = (len(qids) + wikidata_batch - 1) // wikidata_batch

    for i in range(0, len(qids), wikidata_batch):
        batch = qids[i: i + wikidata_batch]
        batch_num = i // wikidata_batch + 1
        try:
            results = fetch_capital_coords(batch)
            capital_coords.update(results)
            log(f"  [CapCoord] Batch {batch_num}/{total_wikidata_batches}: {len(results)} results")
        except Exception as e:
            cap_coord_errors.append({"batch_start": i, "ids": batch, "error": str(e)})
            log(f"  [CapCoord] Batch {batch_num} ERROR: {e}")
        time.sleep(1.5)  # rate limit for Wikidata

    # Retry errors
    if cap_coord_errors:
        log(f"  [CapCoord] Retrying {len(cap_coord_errors)} failed batches...")
        for err in cap_coord_errors:
            try:
                time.sleep(3)
                results = fetch_capital_coords(err["ids"])
                capital_coords.update(results)
            except Exception as e:
                log(f"  [CapCoord] Retry failed: {e}")

    log(f"[Extract-Loc] Found capital coordinates for {len(capital_coords)} entities")

    # ========================================
    # Step 4: Capital -> P17 (country) via QLEVER
    # ========================================
    log("[Extract-Loc] Step 4: Querying capital -> country (QLEVER)...")
    capital_countries, cap_errors = batch_query(fetch_capital_country, qids, "P36")
    log(f"[Extract-Loc] Found capital->country for {len(capital_countries)} entities")

    # ========================================
    # === Matching phase ===
    # ========================================
    log("[Extract-Loc] === Matching to modern countries ===")
    output = {}

    def try_match_modern(targets, source_label):
        """Try matching target list to modern_country (by ID then name)."""
        for t in targets:
            tid = t["target_id"]
            if tid in modern_by_id:
                return {
                    "country_name": modern_by_id[tid]["name"],
                    "iso_a3_code": modern_by_id[tid]["iso_a3_code"],
                    "source": source_label,
                    "via_id": tid,
                }
        for t in targets:
            tn = t["target_name"]
            if tn in modern_by_name:
                return {
                    "country_name": tn,
                    "iso_a3_code": modern_by_name[tn]["iso_a3_code"],
                    "source": source_label,
                }
            if tn.lower() in modern_names_lower:
                info = modern_names_lower[tn.lower()]
                return {
                    "country_name": info["name"],
                    "iso_a3_code": info["iso_a3_code"],
                    "source": source_label,
                }
        return None

    def try_match_mapped_nat(targets, source_label):
        """Try matching target list to already-mapped nationalities."""
        for t in targets:
            tid = t["target_id"]
            if tid in mapped_nats:
                mn = mapped_nats[tid]
                # Verify the country exists in modern_country
                if mn["iso_a3_code"] in iso3_to_name:
                    return {
                        "country_name": mn["country_name"],
                        "iso_a3_code": mn["iso_a3_code"],
                        "source": source_label,
                        "via_mapped_nat": tid,
                    }
        return None

    for qid, name, count in unmapped:
        if qid in level1_relations:
            rels = [r for r in level1_relations[qid] if r["target_id"] != qid]

            # Strategy 1a: Direct match to modern_country
            match = try_match_modern(rels, "L1_modern")
            if match:
                output[qid] = match
                continue

            # Strategy 1b: Match to already-mapped nationality
            match = try_match_mapped_nat(rels, "L1_mapped_nat")
            if match:
                output[qid] = match
                continue

            # Strategy 2: Follow level-2 targets
            for r in rels:
                tid = r["target_id"]
                if tid in level2_relations:
                    l2_rels = level2_relations[tid]
                    match = try_match_modern(l2_rels, f"L2_modern_via_{r['relation']}")
                    if match:
                        output[qid] = match
                        break
                    match = try_match_mapped_nat(l2_rels, f"L2_mapped_nat_via_{r['relation']}")
                    if match:
                        output[qid] = match
                        break
            if qid in output:
                continue

    # Strategy 3: Capital city coordinates -> reverse geocode
    still_unmapped_qids = [q for q in qids if q not in output]
    coords_for_geocode = {q: capital_coords[q] for q in still_unmapped_qids if q in capital_coords}

    if coords_for_geocode:
        log(f"[Extract-Loc] Reverse geocoding {len(coords_for_geocode)} capital city coords...")
        try:
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

            coord_items = list(coords_for_geocode.items())
            coords_list = [(v["lat"], v["lon"]) for _, v in coord_items]
            geo_results = rg.search(coords_list)

            geocoded = 0
            for idx, (qid, coord_info) in enumerate(coord_items):
                cc2 = geo_results[idx]["cc"]
                cc3 = ALPHA2_TO_ALPHA3.get(cc2)
                if cc3 and cc3 in iso3_to_name:
                    output[qid] = {
                        "country_name": iso3_to_name[cc3],
                        "iso_a3_code": cc3,
                        "source": "capital_geocode",
                        "capital": coord_info.get("capital", ""),
                    }
                    geocoded += 1
            log(f"[Extract-Loc] Geocoded {geocoded} from capital coordinates")
        except ImportError:
            log("[Extract-Loc] reverse_geocoder not available")

    # Strategy 4: Capital -> P17 (country of capital) for remaining
    still_unmapped_qids = [q for q in qids if q not in output]
    for qid in still_unmapped_qids:
        if qid in capital_countries:
            for cap in capital_countries[qid]:
                cid = cap["country_id"]
                cn = cap["country_name"]
                if cid in modern_by_id:
                    output[qid] = {
                        "country_name": modern_by_id[cid]["name"],
                        "iso_a3_code": modern_by_id[cid]["iso_a3_code"],
                        "source": "capital_P17",
                    }
                    break
                if cn in modern_by_name:
                    output[qid] = {
                        "country_name": cn,
                        "iso_a3_code": modern_by_name[cn]["iso_a3_code"],
                        "source": "capital_P17",
                    }
                    break
                if cn.lower() in modern_names_lower:
                    info = modern_names_lower[cn.lower()]
                    output[qid] = {
                        "country_name": info["name"],
                        "iso_a3_code": info["iso_a3_code"],
                        "source": "capital_P17",
                    }
                    break

    # === Summary ===
    still_unmapped = [q for q in qids if q not in output]
    log(f"\n[Extract-Loc] === RESULTS ===")
    log(f"[Extract-Loc] Total unmapped: {len(unmapped)}")
    log(f"[Extract-Loc] Mapped: {len(output)}")
    log(f"[Extract-Loc] Still unmapped: {len(still_unmapped)}")

    sources = {}
    for qid, info in output.items():
        src = info["source"].split("(")[0].split("_via_")[0]
        sources[src] = sources.get(src, 0) + 1
    log(f"[Extract-Loc] Source breakdown: {json.dumps(sources, indent=2)}")

    mapped_sorted = sorted(output.items(), key=lambda x: name_lookup.get(x[0], ("", 0))[1] or 0, reverse=True)
    log(f"\n[Extract-Loc] Top 40 mapped:")
    for qid, info in mapped_sorted[:40]:
        name, cnt = name_lookup.get(qid, ("?", 0))
        log(f"  {qid} ({name}, count={cnt}) -> {info['country_name']} ({info['iso_a3_code']}) via {info['source']}")

    still_sorted = sorted(still_unmapped, key=lambda q: name_lookup.get(q, ("", 0))[1] or 0, reverse=True)
    log(f"\n[Extract-Loc] Top 30 still unmapped:")
    for qid in still_sorted[:30]:
        name, cnt = name_lookup.get(qid, ("?", 0))
        rels = level1_relations.get(qid, [])
        rel_str = "; ".join([f"{r['relation']}:{r['target_name']}({r['target_id']})" for r in rels[:3]])
        log(f"  {qid} ({name}, count={cnt}) [{rel_str}]")

    # Save
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    log(f"\n[Extract-Loc] Saved {len(output)} mappings to {OUTPUT_PATH}")

    all_errors = {
        "level1_errors": level1_errors,
        "capital_errors": cap_errors,
        "still_unmapped": [
            {"qid": q, "name": name_lookup.get(q, ("?", 0))[0], "count": name_lookup.get(q, ("?", 0))[1]}
            for q in still_sorted
        ],
    }
    with open(ERRORS_PATH, "w") as f:
        json.dump(all_errors, f, ensure_ascii=False, indent=2)
    log(f"[Extract-Loc] Saved error info to {ERRORS_PATH}")

    log("[Extract-Loc] === Done ===")


if __name__ == "__main__":
    main()
