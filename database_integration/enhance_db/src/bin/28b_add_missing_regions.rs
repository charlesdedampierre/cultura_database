/// Add ALL missing countries to the regions table so every country in the
/// database belongs to at least one region.
/// New macro-regions: North America, Latin America, Sub-Saharan Africa, Oceania, Southeast Asia
/// Also adds small European/Asian territories to existing macro-regions.
use anyhow::Result;
use rusqlite::Connection;
use std::collections::HashSet;
use std::fs;
use std::io::Write;

const DB_PATH: &str = "data/humans_clean.sqlite3";
const TASK_LOG: &str = "task.log";

fn log(msg: &str) {
    println!("{}", msg);
    let mut f = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(TASK_LOG)
        .unwrap();
    writeln!(f, "{}", msg).unwrap();
}

/// All new region mappings for countries not yet in the regions table
/// (macro_region, region, iso_country_name, iso_a3, start_year, end_year)
fn get_new_region_data() -> Vec<(&'static str, &'static str, &'static str, &'static str, i32, Option<i32>)> {
    vec![
        // =====================================================
        // NORTH AMERICA
        // =====================================================
        ("North America", "North America", "United States", "USA", -10000, None),
        ("North America", "North America", "Canada", "CAN", -10000, None),
        ("North America", "North America", "Bermuda", "BMU", -10000, None),
        ("North America", "North America", "Saint Pierre and Miquelon", "SPM", -10000, None),
        ("North America", "North America", "Greenland", "GRL", -10000, None),

        // =====================================================
        // LATIN AMERICA - Central America
        // =====================================================
        ("Latin America", "Central America", "Mexico", "MEX", -10000, None),
        ("Latin America", "Central America", "Guatemala", "GTM", -10000, None),
        ("Latin America", "Central America", "El Salvador", "SLV", -10000, None),
        ("Latin America", "Central America", "Honduras", "HND", -10000, None),
        ("Latin America", "Central America", "Nicaragua", "NIC", -10000, None),
        ("Latin America", "Central America", "Costa Rica", "CRI", -10000, None),
        ("Latin America", "Central America", "Panama", "PAN", -10000, None),
        ("Latin America", "Central America", "Belize", "BLZ", -10000, None),

        // =====================================================
        // LATIN AMERICA - Caribbean
        // =====================================================
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
        ("Latin America", "Caribbean", "CuraÃ§ao", "CUW", -10000, None),
        ("Latin America", "Caribbean", "Saint BarthÃ©lemy", "BLM", -10000, None),
        ("Latin America", "Caribbean", "Sint Maarten", "SXM", -10000, None),

        // =====================================================
        // LATIN AMERICA - South America
        // =====================================================
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

        // =====================================================
        // SUB-SAHARAN AFRICA - West Africa
        // =====================================================
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
        ("Sub-Saharan Africa", "West Africa", "SÃ£o TomÃ© and PrÃ­ncipe", "STP", -10000, None),
        ("Sub-Saharan Africa", "West Africa", "Mauritania", "MRT", -10000, None),

        // =====================================================
        // SUB-SAHARAN AFRICA - East Africa
        // =====================================================
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
        ("Sub-Saharan Africa", "East Africa", "RÃ©union", "REU", -10000, None),
        ("Sub-Saharan Africa", "East Africa", "Mayotte", "MYT", -10000, None),

        // =====================================================
        // SUB-SAHARAN AFRICA - Central Africa
        // =====================================================
        ("Sub-Saharan Africa", "Central Africa", "Democratic Republic of the Congo", "COD", -10000, None),
        ("Sub-Saharan Africa", "Central Africa", "Republic of the Congo", "COG", -10000, None),
        ("Sub-Saharan Africa", "Central Africa", "Central African Republic", "CAF", -10000, None),
        ("Sub-Saharan Africa", "Central Africa", "Chad", "TCD", -10000, None),
        ("Sub-Saharan Africa", "Central Africa", "Gabon", "GAB", -10000, None),
        ("Sub-Saharan Africa", "Central Africa", "Angola", "AGO", -10000, None),
        ("Sub-Saharan Africa", "Central Africa", "Equatorial Guinea", "GNQ", -10000, None),

        // =====================================================
        // SUB-SAHARAN AFRICA - Southern Africa
        // =====================================================
        ("Sub-Saharan Africa", "Southern Africa", "South Africa", "ZAF", -10000, None),
        ("Sub-Saharan Africa", "Southern Africa", "Botswana", "BWA", -10000, None),
        ("Sub-Saharan Africa", "Southern Africa", "Namibia", "NAM", -10000, None),
        ("Sub-Saharan Africa", "Southern Africa", "Eswatini", "SWZ", -10000, None),
        ("Sub-Saharan Africa", "Southern Africa", "Lesotho", "LSO", -10000, None),

        // =====================================================
        // ASIA - Southeast Asia
        // =====================================================
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

        // =====================================================
        // ASIA - Central Asia
        // =====================================================
        ("Asia", "Central Asia", "Kazakhstan", "KAZ", -10000, None),
        ("Asia", "Central Asia", "Tajikistan", "TJK", -10000, None),

        // =====================================================
        // ASIA - Chinese World (additions)
        // =====================================================
        ("Asia", "Chinese World", "Hong Kong", "HKG", -10000, None),
        ("Asia", "Chinese World", "Macau", "MAC", -10000, None),

        // =====================================================
        // ASIA - Indian World (additions)
        // =====================================================
        ("Asia", "Indian World", "Maldives", "MDV", -10000, None),
        ("Asia", "Indian World", "Bhutan", "BTN", -10000, None),

        // =====================================================
        // EASTERN EUROPE - Caucasus
        // =====================================================
        ("Eastern Europe", "Caucasus", "Georgia", "GEO", -10000, None),
        ("Eastern Europe", "Caucasus", "Armenia", "ARM", -10000, None),

        // =====================================================
        // EASTERN EUROPE - East Slavic (additions)
        // =====================================================
        ("Eastern Europe", "East Slavic", "Moldova", "MDA", 500, None),
        ("Eastern Europe", "East Slavic", "Soviet Union", "SUN", 500, None),

        // =====================================================
        // WESTERN EUROPE - additions to existing regions
        // =====================================================
        // Italian world
        ("Western Europe", "Italy", "Vatican City", "VAT", 500, None),
        ("Western Europe", "Italy", "San Marino", "SMR", 500, None),
        ("Western Europe", "Italy", "Malta", "MLT", 500, None),

        // Low countries
        ("Western Europe", "Low countries", "Luxembourg", "LUX", 500, None),

        // German world
        ("Western Europe", "German world", "Liechtenstein", "LIE", 500, None),

        // France
        ("Western Europe", "France", "Monaco", "MCO", 500, None),
        ("Western Europe", "France", "Andorra", "AND", 500, None),

        // British Islands
        ("Western Europe", "British Islands", "Gibraltar", "GIB", 500, None),
        ("Western Europe", "British Islands", "Isle of Man", "IMN", 500, None),
        ("Western Europe", "British Islands", "Guernsey", "GGY", 500, None),

        // Nordic countries
        ("Western Europe", "Nordic countries", "Faroe Islands", "FRO", 500, None),
        ("Western Europe", "Nordic countries", "Svalbard and Jan Mayen", "SJM", 500, None),

        // =====================================================
        // OCEANIA - Australia and New Zealand
        // =====================================================
        ("Oceania", "Australia and New Zealand", "Australia", "AUS", -10000, None),
        ("Oceania", "Australia and New Zealand", "New Zealand", "NZL", -10000, None),
        ("Oceania", "Australia and New Zealand", "Norfolk Island", "NFK", -10000, None),
        ("Oceania", "Australia and New Zealand", "Cocos (Keeling) Islands", "CCK", -10000, None),
        ("Oceania", "Australia and New Zealand", "Christmas Island", "CXR", -10000, None),

        // =====================================================
        // OCEANIA - Melanesia
        // =====================================================
        ("Oceania", "Melanesia", "Papua New Guinea", "PNG", -10000, None),
        ("Oceania", "Melanesia", "Fiji", "FJI", -10000, None),
        ("Oceania", "Melanesia", "Solomon Islands", "SLB", -10000, None),
        ("Oceania", "Melanesia", "Vanuatu", "VUT", -10000, None),
        ("Oceania", "Melanesia", "New Caledonia", "NCL", -10000, None),

        // =====================================================
        // OCEANIA - Polynesia
        // =====================================================
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

        // =====================================================
        // OCEANIA - Micronesia
        // =====================================================
        ("Oceania", "Micronesia", "Federated States of Micronesia", "FSM", -10000, None),
        ("Oceania", "Micronesia", "Kiribati", "KIR", -10000, None),
        ("Oceania", "Micronesia", "Nauru", "NRU", -10000, None),
        ("Oceania", "Micronesia", "Palau", "PLW", -10000, None),
        ("Oceania", "Micronesia", "Marshall Islands", "MHL", -10000, None),
        ("Oceania", "Micronesia", "Guam", "GUM", -10000, None),
        ("Oceania", "Micronesia", "Northern Mariana Islands", "MNP", -10000, None),

        // =====================================================
        // Remaining territories
        // =====================================================
        // Saint Helena -> Sub-Saharan Africa / Southern Africa
        ("Sub-Saharan Africa", "Southern Africa", "Saint Helena, Ascension and Tristan da Cunha", "SHN", -10000, None),
        // French Southern Lands -> Oceania (remote)
        ("Oceania", "Australia and New Zealand", "French Southern and Antarctic Lands", "ATF", -10000, None),
        // Western Sahara -> MENA / Arabic world
        ("Middle-East and Africa (MENA)", "Arabic world", "Western Sahara", "ESH", -10000, None),
        // Qatar -> MENA / Arabic world
        ("Middle-East and Africa (MENA)", "Arabic world", "Qatar", "QAT", -10000, None),
    ]
}

fn main() -> Result<()> {
    log("=== Step 28b: Add missing regions for ALL countries ===");

    let conn = Connection::open(DB_PATH)?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-2000000;",
    )?;

    // Get existing iso_a3 codes in regions table
    let mut existing: HashSet<String> = HashSet::new();
    {
        let mut stmt = conn.prepare("SELECT DISTINCT iso_a3 FROM regions")?;
        let rows = stmt.query_map([], |r| r.get::<_, String>(0))?;
        for r in rows {
            existing.insert(r?);
        }
    }
    log(&format!("[28b] Existing region entries cover {} ISO codes", existing.len()));

    let data = get_new_region_data();
    let mut inserted = 0;
    let mut skipped = 0;

    conn.execute_batch("BEGIN TRANSACTION;")?;
    {
        let mut stmt = conn.prepare(
            "INSERT INTO regions (macro_region, region, iso_country_name, iso_a3, start_year, end_year)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
        )?;

        for (macro_region, region, country, iso, start, end) in &data {
            // Check if this specific (iso_a3, region) combo already exists
            let already: bool = {
                let mut check = conn.prepare_cached(
                    "SELECT COUNT(*) FROM regions WHERE iso_a3 = ?1 AND region = ?2"
                )?;
                let cnt: i64 = check.query_row(rusqlite::params![iso, region], |r| r.get(0))?;
                cnt > 0
            };

            if already {
                skipped += 1;
            } else {
                stmt.execute(rusqlite::params![macro_region, region, country, iso, start, end])?;
                inserted += 1;
            }
        }
    }
    conn.execute_batch("COMMIT;")?;

    log(&format!("[28b] Inserted {} new region-country mappings, skipped {} duplicates", inserted, skipped));

    // Check for any remaining unmapped countries
    let total_regions: i64 = conn.query_row("SELECT COUNT(*) FROM regions", [], |r| r.get(0))?;
    let distinct_iso: i64 = conn.query_row("SELECT COUNT(DISTINCT iso_a3) FROM regions", [], |r| r.get(0))?;
    log(&format!("[28b] Total rows in regions: {}", total_regions));
    log(&format!("[28b] Distinct ISO codes covered: {}", distinct_iso));

    // Check which countries in individuals_countries still have no region
    let table_exists: bool = conn.query_row(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='individuals_countries'",
        [], |r| r.get::<_, i64>(0)
    ).map(|c| c > 0).unwrap_or(false);

    if table_exists {
        let mut stmt = conn.prepare(
            "SELECT DISTINCT ic.iso_country_name, ic.iso_a3_code, COUNT(*) as cnt
             FROM individuals_countries ic
             LEFT JOIN regions r ON ic.iso_a3_code = r.iso_a3
             WHERE r.iso_a3 IS NULL
             GROUP BY ic.iso_country_name, ic.iso_a3_code
             ORDER BY cnt DESC"
        )?;
        let unmapped: Vec<(String, String, i64)> = stmt
            .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?
            .filter_map(|r| r.ok())
            .collect();

        if unmapped.is_empty() {
            log("[28b] All countries in individuals_countries now have a region mapping!");
        } else {
            log(&format!("[28b] WARNING: {} countries still unmapped:", unmapped.len()));
            for (name, iso, cnt) in &unmapped {
                log(&format!("[28b]   {} ({}) -> {} individuals", name, iso, cnt));
            }
        }
    } else {
        log("[28b] individuals_countries table not yet created, skipping unmapped check");
    }

    // Summary by macro_region
    let mut stmt = conn.prepare(
        "SELECT macro_region, COUNT(*) FROM regions GROUP BY macro_region ORDER BY macro_region",
    )?;
    let rows: Vec<(String, i64)> = stmt
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
        .filter_map(|r| r.ok())
        .collect();
    log("[28b] Summary by macro_region (after additions):");
    for (mr, cnt) in &rows {
        log(&format!("[28b]   {} -> {} country mappings", mr, cnt));
    }

    log("=== Step 28b complete ===");
    Ok(())
}
