use anyhow::{Context, Result};
use clap::Parser;
use indicatif::{ProgressBar, ProgressStyle};
use regex::Regex;
use rusqlite::{params, Connection, OpenFlags};
use std::path::PathBuf;
use std::time::Instant;

#[derive(Parser, Debug)]
#[command(about = "Extract dates from individuals.description_en into individuals.dates_in_description")]
struct Args {
    /// Path to humans_clean.sqlite3
    #[arg(long)]
    db: PathBuf,

    /// Process only this many rows (0 = all)
    #[arg(long, default_value_t = 0)]
    sample: usize,

    /// Don't write back; just print stats and a few examples
    #[arg(long, default_value_t = false)]
    dry_run: bool,

    /// Rows per UPDATE transaction
    #[arg(long, default_value_t = 50_000)]
    batch_size: usize,

    /// How many positive examples to print
    #[arg(long, default_value_t = 30)]
    examples: usize,
}

const MONTH: &str =
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)";

// Qualifiers tolerated inside ranges and around years: "Bef", "Aft", "before",
// "after", "circa", "ca.", "c.", "certain", "uncertain", "est.", "estimated",
// "Abt", "about", "probably".
const QUAL: &str = r"(?:after|before|aft\.?|bef\.?|circa|ca\.?|c\.?|certain|uncertain|est\.?|estimated|abt\.?|about|probably|approximately)";

struct Extractor {
    re_marker: Regex,
    re_dmy_range: Regex,
    re_dmy_to_year: Regex,
    re_year_to_dmy: Regex,
    re_my_to_my: Regex,
    re_my_to_year: Regex,
    re_year_to_my: Regex,
    re_dmy_to_my: Regex,
    re_my_to_dmy: Regex,
    re_from_to: Regex,
    re_between: Regex,
    re_decade_range: Regex,
    re_circa_suffix_range: Regex,
    re_yyyy_yy_range: Regex,
    re_range: Regex,
    re_loose_range: Regex,
    re_paren_short_range: Regex,
    re_paren_open_birth: Regex,
    re_paren_open_death: Regex,
    re_trailing_open_birth: Regex,
    re_dmy_open_birth: Regex,
    re_leading_open_death: Regex,
    re_dash_qualifier_year: Regex,
    re_dash_my: Regex,
    re_dash_dmy: Regex,
    re_active: Regex,
    re_fl: Regex,
    re_exhibited: Regex,
    re_born: Regex,
    re_died: Regex,
    re_year_at_start: Regex,
    re_century: Regex,
    re_century_range: Regex,
    re_half_century: Regex,
    re_early_late_century: Regex,
    re_fl_century: Regex,
    re_id_chain: Regex,
    re_degree: Regex,
}

impl Extractor {
    fn new() -> Self {
        // year + marker, marker + year, or marker glued to year (e.g. "b.c.1946", "AD10").
        let marker_pat = r"(?ix)
            \b
            (?:
                (?P<y1>\d{1,4})\s*[.\-]?\s*
                (?P<m1>B\.?C\.?E\.?|B\.?C\.?|B\.?C\.E\.?|A\.?D\.?|C\.?E\.?|A\.?C\.?)
                |
                (?P<m2>B\.?C\.?E\.?|B\.?C\.?|B\.?C\.E\.?|A\.?D\.?|C\.?E\.?|A\.?C\.?)\s*
                (?P<y2>\d{1,4})
            )
            \b
        ";

        // === DAY-MONTH-YEAR family ===
        // Each side of the dash tolerates up to 25 non-dash / non-digit characters of
        // noise (location names, qualifiers, parens) so e.g. "1693 Leiden - 18 Sep 1762
        // Leiden" still parses as a range.
        const NOISE_L: &str = r"[^-\u{2013}\u{2014}\d\n]{0,25}?";
        const NOISE_R: &str = r"[^\d\n]{0,25}?";

        // "DD Mon YYYY - DD Mon YYYY"
        let dmy_range_pat = format!(
            r"(?ix)
            \b\d{{1,2}}\s+{m}\s+(?P<r1>\d{{3,4}})
            {nl}
            [-\u{{2013}}\u{{2014}}]
            {nr}
            (?:{q}\s+)*
            \d{{1,2}}\s+{m}\s+(?P<r2>\d{{3,4}})
            ",
            m = MONTH, q = QUAL, nl = NOISE_L, nr = NOISE_R
        );
        // "DD Mon YYYY - YYYY"  (right side has only year)
        let dmy_to_year_pat = format!(
            r"(?ix)
            \b\d{{1,2}}\s+{m}\s+(?P<dy_a>\d{{3,4}})
            {nl}
            [-\u{{2013}}\u{{2014}}]\s*
            (?:{q}\s+)*
            (?P<dy_b>\d{{3,4}})\b
            ",
            m = MONTH, q = QUAL, nl = NOISE_L
        );
        // "YYYY - DD Mon YYYY"
        let year_to_dmy_pat = format!(
            r"(?ix)
            \b(?P<yd_a>\d{{3,4}})
            \s*[-\u{{2013}}\u{{2014}}]
            {nr}
            (?:{q}\s+)*
            \d{{1,2}}\s+{m}\s+(?P<yd_b>\d{{3,4}})\b
            ",
            m = MONTH, q = QUAL, nr = NOISE_R
        );
        // "Mon YYYY - Mon YYYY"
        let my_to_my_pat = format!(
            r"(?ix)
            \b{m}\s+(?P<mm_a>\d{{3,4}})
            \s*[-\u{{2013}}\u{{2014}}]\s*
            (?:{q}\s+)*
            {m}\s+(?P<mm_b>\d{{3,4}})\b
            ",
            m = MONTH, q = QUAL
        );
        // "Mon YYYY - YYYY"
        let my_to_year_pat = format!(
            r"(?ix)
            \b{m}\s+(?P<my_a>\d{{3,4}})
            \s*[-\u{{2013}}\u{{2014}}]\s*
            (?:{q}\s+)*
            (?P<my_b>\d{{3,4}})\b
            ",
            m = MONTH, q = QUAL
        );
        // "YYYY - Mon YYYY"
        let year_to_my_pat = format!(
            r"(?ix)
            \b(?P<ym_a>\d{{3,4}})
            \s*[-\u{{2013}}\u{{2014}}]\s*
            (?:{q}\s+)*
            {m}\s+(?P<ym_b>\d{{3,4}})\b
            ",
            m = MONTH, q = QUAL
        );
        // "DD Mon YYYY - Mon YYYY"
        let dmy_to_my_pat = format!(
            r"(?ix)
            \b\d{{1,2}}\s+{m}\s+(?P<dmm_a>\d{{3,4}})
            \s*[-\u{{2013}}\u{{2014}}]\s*
            (?:{q}\s+)*
            {m}\s+(?P<dmm_b>\d{{3,4}})\b
            ",
            m = MONTH, q = QUAL
        );
        // "Mon YYYY - DD Mon YYYY"
        let my_to_dmy_pat = format!(
            r"(?ix)
            \b{m}\s+(?P<mdm_a>\d{{3,4}})
            \s*[-\u{{2013}}\u{{2014}}]\s*
            (?:{q}\s+)*
            \d{{1,2}}\s+{m}\s+(?P<mdm_b>\d{{3,4}})\b
            ",
            m = MONTH, q = QUAL
        );

        // === YEAR-ONLY ranges ===
        // "from YYYY to YYYY"
        let from_to_pat = r"(?ix)
            \bfrom\s+(?P<ft_a>\d{3,4})\s+to\s+(?P<ft_b>\d{3,4})\b
        ";
        // "between YYYY and YYYY"
        let between_pat = r"(?ix)
            \bbetween\s+(?P<bt_a>\d{3,4})\s+and\s+(?P<bt_b>\d{3,4})\b
        ";
        // Decade range "(1780s-1840s)" / "1780s - 1840s"
        let decade_range_pat = r"(?x)
            \b(?P<dr_a>\d{4})s
            \s*[-\u{2013}\u{2014}]\s*
            (?P<dr_b>\d{4})s\b
        ";
        // Circa-suffix range "1771c-1845c"
        let circa_suffix_range_pat = r"(?x)
            \b(?P<cs_a>\d{4})c
            \s*[-\u{2013}\u{2014}]\s*
            (?P<cs_b>\d{4})c\b
        ";
        // "(YYYY-YY)" 2-digit-suffix range — parentheses required for safety.
        let yyyy_yy_range_pat = r"(?x)
            \(\s*(?P<yy_a>\d{4})\s*[-\u{2013}\u{2014}]\s*(?P<yy_b>\d{2})\s*\)
        ";
        // 4-digit "YYYY-YYYY" adjacent.
        let range_pat = r"(?x)
            (?P<a>\d{4})
            \s*[-\u{2013}\u{2014}]\s*
            (?P<b>\d{4})
        ";
        // Loose "YYYY [stuff] - [stuff] YYYY" — gap up to 25 non-digit chars on each
        // side. Catches "1879 Cesena - 1965 Cesena", "1343 - before 1376",
        // "1702-after 1750", "1885 - ? 1946", "Abt 1300 - Aft 1331".
        // We require at least one of the gaps to be non-empty so plain "YYYY-YYYY"
        // is left to re_range (which has stricter validation).
        let loose_range_pat = r"(?x)
            \b(?P<lr_a>\d{4})
            (?P<lr_g1>[^\d\n]{0,25}?)
            [-\u{2013}\u{2014}]
            (?P<lr_g2>[^\d\n]{0,25}?)
            (?P<lr_b>\d{4})\b
        ";
        // 2-3-4 digit ranges inside parens — for "(37-68)", "(99-180)", "(850-920)".
        let paren_short_range_pat = r"(?x)
            \(
            \s*(?P<sa>\d{2,4})
            \s*[-\u{2013}\u{2014}]\s*
            (?P<sb>\d{2,4})\s*
            \)
        ";

        // === OPEN birth ===
        // "(YYYY-)" / "(YYYY-?)" / "(YYYY - uncertain)" / "(est. YYYY -)"
        let paren_open_birth_pat = r"(?ix)
            \(
            \s*(?:est\.?|circa|ca\.?|c\.|abt\.?|estimated|approximately)?\s*
            (?P<pob>\d{3,4})\s*
            [-\u{2013}\u{2014}]
            \s*(?:\?|uncertain|unknown|no\s+date)?\s*
            \)
        ";
        // Trailing "YYYY-" / "YYYY -" at end of string.
        let trailing_open_birth_pat = r"(?x)
            \b(?P<tob>\d{4})\s*[-\u{2013}\u{2014}]\s*$
        ";
        // "DD Mon YYYY - )" / "DD Mon YYYY - $"
        let dmy_open_birth_pat = format!(
            r"(?ix)
            \b\d{{1,2}}\s+{m}\s+(?P<dmob>\d{{3,4}})
            \s*[-\u{{2013}}\u{{2014}}]\s*
            (?:\)|$)
            ",
            m = MONTH
        );

        // === OPEN death ===
        // "(-YYYY)" / "(- YYYY)"
        let paren_open_death_pat = r"(?x)
            \(
            \s*[-\u{2013}\u{2014}]\s*
            (?P<pod>\d{3,4})\s*
            \)
        ";
        // Leading "-YYYY" / "- YYYY" at description start.
        let leading_open_death_pat = r"(?x)
            ^\s*
            [-\u{2013}\u{2014}]\s*
            (?P<lod>\d{3,4})\b
        ";
        // "- Bef/Aft/before/after YYYY" anywhere.
        let dash_qualifier_year_pat = format!(
            r"(?ix)
            (?:^|[\s\(])
            [-\u{{2013}}\u{{2014}}]\s*
            (?:{q}\s+)+
            (?P<dqy>\d{{3,4}})\b
            ",
            q = QUAL
        );
        // "- Mon YYYY" (no day): "- Aug 1464"
        let dash_my_pat = format!(
            r"(?ix)
            (?:^|[\s\(])
            [-\u{{2013}}\u{{2014}}]\s*
            (?:{q}\s+)*
            {m}\s+(?P<dmy_my>\d{{3,4}})\b
            ",
            m = MONTH, q = QUAL
        );
        // "- DD Mon YYYY" orphan.
        let dash_dmy_pat = format!(
            r"(?ix)
            (?:^|[\s\(])
            [-\u{{2013}}\u{{2014}}]\s*
            (?:{q}\s+)*
            \d{{1,2}}\s+{m}\s+(?P<dmy_y>\d{{3,4}})
            \b
            ",
            m = MONTH, q = QUAL
        );

        // === KEYWORD-anchored single years ===
        // "active [...] YYYY"
        let active_pat = r"(?ix)
            \bactive\b
            (?:\s+(?:ca\.?|circa|c\.|in))?
            \s+(?P<ay>\d{3,4})
            (?:s)?
            \b
        ";
        // "fl. [...] YYYY"
        let fl_pat = r"(?ix)
            \bfl\.?
            (?:\s+(?:ca\.?|circa|c\.|in))*
            \s+(?P<fy>\d{3,4})
            (?:s)?
            \b
        ";
        // "exhibited YYYY" / "exhibited in YYYY"
        let exhibited_pat = r"(?ix)
            \bexhibited\b
            (?:\s+(?:in|at|ca\.?|circa|c\.))?
            \s+(?P<ey>\d{3,4})
            \b
        ";
        // "born/baptized [...] YYYY" or "b./bap./bapt. YYYY"
        let born_pat = r"(?ix)
            \b(?:born|baptized|baptised|b\.|bap\.?|bapt\.?)
            (?:.{0,40}?)?
            \b(?P<by>\d{3,4})\b
        ";
        // "died/buried [...] YYYY" or "d./bur. YYYY"
        let died_pat = r"(?ix)
            \b(?:died|buried|d\.|bur\.?)
            (?:.{0,40}?)?
            \b(?P<dy2>\d{3,4})\b
        ";

        // === BARE year at description start ===
        // "^YYYY" or "^Abt YYYY" with the rest being non-digit text → b YYYY.
        let year_at_start_pat = r"(?ix)
            ^\s*
            (?:abt\.?\s+)?
            (?P<sy>\d{3,4})
            (?:\b|$)
        ";

        // === CENTURIES ===
        // "first/second half of (the) Nth century [BC]" → fl <signed midpoint>.
        // Same for "early Nth century", "mid Nth century", "late Nth century".
        // We emit a fl-token directly so the half-precision year survives into the
        // floruit_year_in_description column.
        let half_century_pat = r"(?ix)
            \b
            (?P<hmod>first|second|early|late|mid|middle)
            \s+
            (?:half\s+of\s+)?
            (?:the\s+)?
            (?P<hcn>\d{1,2})\s*(?:st|nd|rd|th)
            [\s\-]
            centur(?:y|ies)
            (?:\s+(?P<hmk>B\.?C\.?E\.?|B\.?C\.?))?
            \b
        ";
        // "early-Nth century" / "late-Nth century" with hyphen.
        let early_late_century_pat = r"(?ix)
            \b
            (?P<elmod>early|late|mid)
            -
            (?P<elcn>\d{1,2})\s*(?:st|nd|rd|th)
            [\s\-]
            centur(?:y|ies)
            (?:\s+(?P<elmk>B\.?C\.?E\.?|B\.?C\.?))?
            \b
        ";

        // "fl. Nth century" / "active Nth century" / "flourished in the Nth
        // century" → fl <signed midpoint>. Run *before* the half/plain century
        // passes so it claims the matched span first; otherwise the same span
        // would also emit a bare `cN` token and the floruit would later be set
        // implicitly even though the user wants century-only mentions to leave
        // floruit empty.
        let fl_century_pat = r"(?ix)
            \b
            (?:fl\.?|flourished|active)
            \s+
            (?:(?:in|during)\s+)?
            (?:the\s+)?
            (?:c\.?\s+|circa\s+|ca\.?\s+)?
            (?P<flccn>\d{1,2})\s*(?:st|nd|rd|th)
            [\s\-]
            centur(?:y|ies)
            (?:\s+(?P<flcmk>B\.?C\.?E\.?|B\.?C\.?))?
            \b
        ";

        let century_pat = r"(?ix)
            \b
            (?P<cn>\d{1,2})
            \s*(?:st|nd|rd|th)
            [\s\-]
            centur(?:y|ies)
            (?:\s+(?P<cmk>B\.?C\.?E\.?|B\.?C\.?))?
            \b
        ";
        let century_range_pat = r"(?ix)
            \b
            (?P<cra>\d{1,2})\s*(?:st|nd|rd|th)
            \s*[-\u{2013}\u{2014}]\s*
            (?P<crb>\d{1,2})\s*(?:st|nd|rd|th)
            [\s\-]
            centur(?:y|ies)
            (?:\s+(?P<crmk>B\.?C\.?E\.?|B\.?C\.?))?
            \b
        ";

        // ID-style hyphen-chains: 3 or more digit groups joined by hyphens (ORCID,
        // catalog IDs, phone numbers). Pre-marking these as covered keeps every range
        // pattern below from extracting a year-like pair from inside them.
        let id_chain_pat = r"(?x)
            \b
            \d{1,5}
            (?:-\d{1,5}){2,}
            \b
        ";
        // Academic degree abbreviations like "Ph.D.", "B.A.", "M.D.", "LL.D.", "Ed.D.".
        // Pre-marked so the trailing letter+dot doesn't trip the b./d. abbreviation
        // patterns: "Ph.D. Lund University 1998" was being read as "d 1998".
        let degree_pat = r"(?x)
            \b
            [A-Z][a-zA-Z]?\.\s*
            [A-Z][a-zA-Z]?\.
            (?:\s*[A-Z][a-zA-Z]?\.)?
        ";

        Self {
            re_marker: Regex::new(marker_pat).unwrap(),
            re_dmy_range: Regex::new(&dmy_range_pat).unwrap(),
            re_dmy_to_year: Regex::new(&dmy_to_year_pat).unwrap(),
            re_year_to_dmy: Regex::new(&year_to_dmy_pat).unwrap(),
            re_my_to_my: Regex::new(&my_to_my_pat).unwrap(),
            re_my_to_year: Regex::new(&my_to_year_pat).unwrap(),
            re_year_to_my: Regex::new(&year_to_my_pat).unwrap(),
            re_dmy_to_my: Regex::new(&dmy_to_my_pat).unwrap(),
            re_my_to_dmy: Regex::new(&my_to_dmy_pat).unwrap(),
            re_from_to: Regex::new(from_to_pat).unwrap(),
            re_between: Regex::new(between_pat).unwrap(),
            re_decade_range: Regex::new(decade_range_pat).unwrap(),
            re_circa_suffix_range: Regex::new(circa_suffix_range_pat).unwrap(),
            re_yyyy_yy_range: Regex::new(yyyy_yy_range_pat).unwrap(),
            re_range: Regex::new(range_pat).unwrap(),
            re_loose_range: Regex::new(loose_range_pat).unwrap(),
            re_paren_short_range: Regex::new(paren_short_range_pat).unwrap(),
            re_paren_open_birth: Regex::new(paren_open_birth_pat).unwrap(),
            re_paren_open_death: Regex::new(paren_open_death_pat).unwrap(),
            re_trailing_open_birth: Regex::new(trailing_open_birth_pat).unwrap(),
            re_dmy_open_birth: Regex::new(&dmy_open_birth_pat).unwrap(),
            re_leading_open_death: Regex::new(leading_open_death_pat).unwrap(),
            re_dash_qualifier_year: Regex::new(&dash_qualifier_year_pat).unwrap(),
            re_dash_my: Regex::new(&dash_my_pat).unwrap(),
            re_dash_dmy: Regex::new(&dash_dmy_pat).unwrap(),
            re_active: Regex::new(active_pat).unwrap(),
            re_fl: Regex::new(fl_pat).unwrap(),
            re_exhibited: Regex::new(exhibited_pat).unwrap(),
            re_born: Regex::new(born_pat).unwrap(),
            re_died: Regex::new(died_pat).unwrap(),
            re_year_at_start: Regex::new(year_at_start_pat).unwrap(),
            re_century: Regex::new(century_pat).unwrap(),
            re_century_range: Regex::new(century_range_pat).unwrap(),
            re_half_century: Regex::new(half_century_pat).unwrap(),
            re_early_late_century: Regex::new(early_late_century_pat).unwrap(),
            re_fl_century: Regex::new(fl_century_pat).unwrap(),
            re_id_chain: Regex::new(id_chain_pat).unwrap(),
            re_degree: Regex::new(degree_pat).unwrap(),
        }
    }

    fn normalize_marker(raw: &str) -> &'static str {
        let cleaned: String = raw.chars().filter(|c| c.is_ascii_alphabetic()).collect();
        match cleaned.to_ascii_uppercase().as_str() {
            "BCE" => "BCE",
            "BC" => "BC",
            "AD" => "AD",
            "CE" => "CE",
            "AC" => "AC",
            _ => "BC",
        }
    }

    fn extract(&self, text: &str) -> Option<String> {
        let mut out: Vec<String> = Vec::new();
        let mut covered: Vec<(usize, usize)> = Vec::new();
        let mut born_year: Option<u32> = None;
        let mut died_year: Option<u32> = None;
        let mut range_seen: bool = false;

        let overlaps = |spans: &[(usize, usize)], s: usize, e: usize| -> bool {
            spans.iter().any(|&(a, b)| s < b && a < e)
        };

        // --- 0) Pre-mark ID-style hyphen-chains (ORCID, catalog IDs) and academic
        //        degree abbreviations so no range/born/died pattern extracts from them. ---
        for m in self.re_id_chain.find_iter(text) {
            covered.push((m.start(), m.end()));
        }
        for m in self.re_degree.find_iter(text) {
            covered.push((m.start(), m.end()));
        }

        // --- 1) BC/AD markers (extend covered backward over slashed-year prefixes) ---
        for cap in self.re_marker.captures_iter(text) {
            let m = cap.get(0).unwrap();
            let (year, marker) = if let (Some(y), Some(mk)) = (cap.name("y1"), cap.name("m1")) {
                (y.as_str(), mk.as_str())
            } else if let (Some(y), Some(mk)) = (cap.name("y2"), cap.name("m2")) {
                (y.as_str(), mk.as_str())
            } else {
                continue;
            };
            let year_trimmed = year.trim_start_matches('0');
            let year_clean = if year_trimmed.is_empty() { "0" } else { year_trimmed };
            let token = format!("{} {}", year_clean, Self::normalize_marker(marker));
            let start = extend_back_over_slash(text, m.start());
            covered.push((start, m.end()));
            push_unique(&mut out, token);
        }

        // --- 2) DAY-MONTH-YEAR family (full → asymmetric → month-year forms) ---
        let dmy_specs: &[(&Regex, &str, &str)] = &[
            (&self.re_dmy_range,    "r1",   "r2"),
            (&self.re_dmy_to_my,    "dmm_a","dmm_b"),
            (&self.re_my_to_dmy,    "mdm_a","mdm_b"),
            (&self.re_dmy_to_year,  "dy_a", "dy_b"),
            (&self.re_year_to_dmy,  "yd_a", "yd_b"),
            (&self.re_my_to_my,     "mm_a", "mm_b"),
            (&self.re_my_to_year,   "my_a", "my_b"),
            (&self.re_year_to_my,   "ym_a", "ym_b"),
        ];
        for (re, na, nb) in dmy_specs {
            apply_range(re, na, nb, text, &mut covered, &mut out, &mut range_seen, true);
        }

        // --- 3) "from YYYY to YYYY" / "between YYYY and YYYY" ---
        apply_range(&self.re_from_to,  "ft_a", "ft_b", text, &mut covered, &mut out, &mut range_seen, true);
        apply_range(&self.re_between,  "bt_a", "bt_b", text, &mut covered, &mut out, &mut range_seen, true);

        // --- 4) Decade range "1780s-1840s" → 1780-1840 ---
        apply_range(&self.re_decade_range, "dr_a", "dr_b", text, &mut covered, &mut out, &mut range_seen, true);

        // --- 5) Circa-suffix range "1771c-1845c" ---
        apply_range(&self.re_circa_suffix_range, "cs_a", "cs_b", text, &mut covered, &mut out, &mut range_seen, true);

        // --- 6) "(YYYY-YY)" 2-digit-suffix range, parens required ---
        for cap in self.re_yyyy_yy_range.captures_iter(text) {
            let m = cap.get(0).unwrap();
            if overlaps(&covered, m.start(), m.end()) {
                continue;
            }
            let a: u32 = cap["yy_a"].parse().unwrap_or(0);
            let suf: u32 = cap["yy_b"].parse().unwrap_or(0);
            // Expand suffix using the century of `a`: e.g. 1934 + "35" → 1935.
            let century = (a / 100) * 100;
            let mut b = century + suf;
            if b < a { b += 100; }
            if !sane_year(a) || !sane_year(b) || a > b || b - a > 200 {
                continue;
            }
            covered.push((m.start(), m.end()));
            push_unique(&mut out, format!("{}-{}", a, b));
            range_seen = true;
        }

        // --- 7) Plain "YYYY-YYYY" adjacent, with the original 1000..=2999 guard.
        //     Reject reversed (a > b), and reject when the match is embedded in a
        //     longer hyphen-chain like an ORCID (`0000-0003-2969-2779`). ---
        for cap in self.re_range.captures_iter(text) {
            let m = cap.get(0).unwrap();
            if overlaps(&covered, m.start(), m.end()) {
                continue;
            }
            if in_hyphen_chain(text, m.start(), m.end()) {
                continue;
            }
            let a: u32 = cap["a"].parse().unwrap_or(0);
            let b: u32 = cap["b"].parse().unwrap_or(0);
            if !(1000..=2999).contains(&a) || !(1000..=2999).contains(&b) || a > b {
                continue;
            }
            covered.push((m.start(), m.end()));
            push_unique(&mut out, format!("{}-{}", a, b));
            range_seen = true;
        }

        // --- 8) Loose YYYY-YYYY allowing short non-digit gaps. ---
        for cap in self.re_loose_range.captures_iter(text) {
            let m = cap.get(0).unwrap();
            if overlaps(&covered, m.start(), m.end()) {
                continue;
            }
            let a: u32 = cap["lr_a"].parse().unwrap_or(0);
            let b: u32 = cap["lr_b"].parse().unwrap_or(0);
            if !(1000..=2999).contains(&a) || !(1000..=2999).contains(&b) {
                continue;
            }
            // Years out of order → likely a false positive (e.g. typo); skip.
            if a > b {
                continue;
            }
            covered.push((m.start(), m.end()));
            push_unique(&mut out, format!("{}-{}", a, b));
            range_seen = true;
        }

        // --- 9) Parenthesized 2-3 digit ranges "(37-68)" ---
        for cap in self.re_paren_short_range.captures_iter(text) {
            let m = cap.get(0).unwrap();
            if overlaps(&covered, m.start(), m.end()) {
                continue;
            }
            let a: u32 = cap["sa"].parse().unwrap_or(0);
            let b: u32 = cap["sb"].parse().unwrap_or(0);
            if !(1..=2999).contains(&a) || !(1..=2999).contains(&b) || a > b {
                continue;
            }
            covered.push((m.start(), m.end()));
            push_unique(&mut out, format!("{}-{}", a, b));
            range_seen = true;
        }

        // --- 10) Paren open-birth "(YYYY-)" / "(YYYY-?)" / "(YYYY - uncertain)" ---
        for cap in self.re_paren_open_birth.captures_iter(text) {
            let m = cap.get(0).unwrap();
            if overlaps(&covered, m.start(), m.end()) {
                continue;
            }
            let y: u32 = cap["pob"].parse().unwrap_or(0);
            if !sane_year(y) { continue; }
            covered.push((m.start(), m.end()));
            if born_year.is_none() { born_year = Some(y); }
        }

        // --- 11) Paren open-death "(-YYYY)" ---
        for cap in self.re_paren_open_death.captures_iter(text) {
            let m = cap.get(0).unwrap();
            if overlaps(&covered, m.start(), m.end()) {
                continue;
            }
            let y: u32 = cap["pod"].parse().unwrap_or(0);
            if !sane_year(y) { continue; }
            covered.push((m.start(), m.end()));
            if died_year.is_none() { died_year = Some(y); }
        }

        // --- 12) Trailing "YYYY-" → birth-only ---
        for cap in self.re_trailing_open_birth.captures_iter(text) {
            let m = cap.get(0).unwrap();
            if overlaps(&covered, m.start(), m.end()) {
                continue;
            }
            let y: u32 = cap["tob"].parse().unwrap_or(0);
            if !sane_year(y) { continue; }
            covered.push((m.start(), m.end()));
            if born_year.is_none() { born_year = Some(y); }
        }

        // --- 13) "DD Mon YYYY -" at end of paren or string → birth-only ---
        for cap in self.re_dmy_open_birth.captures_iter(text) {
            let m = cap.get(0).unwrap();
            if overlaps(&covered, m.start(), m.end()) {
                continue;
            }
            let y: u32 = cap["dmob"].parse().unwrap_or(0);
            if !sane_year(y) { continue; }
            covered.push((m.start(), m.end()));
            if born_year.is_none() { born_year = Some(y); }
        }

        // --- 14) Leading "-YYYY" at description start → death-only ---
        for cap in self.re_leading_open_death.captures_iter(text) {
            let m = cap.get(0).unwrap();
            if overlaps(&covered, m.start(), m.end()) {
                continue;
            }
            let y: u32 = cap["lod"].parse().unwrap_or(0);
            if !sane_year(y) { continue; }
            covered.push((m.start(), m.end()));
            if died_year.is_none() { died_year = Some(y); }
        }

        // --- 15) Dash + qualifier + year (Bef/Aft/before/after) → death ---
        // Skip if a range was already parsed (its dash is already accounted for).
        if !range_seen {
            for cap in self.re_dash_qualifier_year.captures_iter(text) {
                let m = cap.get(0).unwrap();
                if overlaps(&covered, m.start(), m.end()) {
                    continue;
                }
                let y: u32 = cap["dqy"].parse().unwrap_or(0);
                if !sane_year(y) { continue; }
                covered.push((m.start(), m.end()));
                if died_year.is_none() { died_year = Some(y); }
            }
            // --- 16) "- Mon YYYY" (month + year, no day) → death ---
            for cap in self.re_dash_my.captures_iter(text) {
                let m = cap.get(0).unwrap();
                if overlaps(&covered, m.start(), m.end()) {
                    continue;
                }
                let y: u32 = cap["dmy_my"].parse().unwrap_or(0);
                if !sane_year(y) { continue; }
                covered.push((m.start(), m.end()));
                if died_year.is_none() { died_year = Some(y); }
            }
            // --- 17) "- DD Mon YYYY" orphan → death ---
            for cap in self.re_dash_dmy.captures_iter(text) {
                let m = cap.get(0).unwrap();
                if overlaps(&covered, m.start(), m.end()) {
                    continue;
                }
                let y: u32 = cap["dmy_y"].parse().unwrap_or(0);
                if !sane_year(y) { continue; }
                covered.push((m.start(), m.end()));
                if died_year.is_none() { died_year = Some(y); }
            }
        }

        // --- 18) Keyword-anchored single years ---
        let fl_specs: &[(&Regex, &str)] = &[
            (&self.re_active, "ay"),
            (&self.re_fl,     "fy"),
            (&self.re_exhibited, "ey"),
        ];
        for (re, name) in fl_specs {
            for cap in re.captures_iter(text) {
                let m = cap.get(0).unwrap();
                if overlaps(&covered, m.start(), m.end()) { continue; }
                let y: u32 = cap[*name].parse().unwrap_or(0);
                if !sane_year(y) { continue; }
                covered.push((m.start(), m.end()));
                push_unique(&mut out, format!("fl {}", y));
            }
        }

        // --- 19) born / died ---
        for cap in self.re_born.captures_iter(text) {
            let m = cap.get(0).unwrap();
            if overlaps(&covered, m.start(), m.end()) { continue; }
            let y: u32 = cap["by"].parse().unwrap_or(0);
            if !sane_year(y) { continue; }
            covered.push((m.start(), m.end()));
            if born_year.is_none() { born_year = Some(y); }
        }
        for cap in self.re_died.captures_iter(text) {
            let m = cap.get(0).unwrap();
            if overlaps(&covered, m.start(), m.end()) { continue; }
            let y: u32 = cap["dy2"].parse().unwrap_or(0);
            if !sane_year(y) { continue; }
            covered.push((m.start(), m.end()));
            if died_year.is_none() { died_year = Some(y); }
        }

        // --- 20) Bare YYYY at description start (only if not already covered) ---
        if let Some(cap) = self.re_year_at_start.captures(text) {
            let m = cap.get(0).unwrap();
            if !overlaps(&covered, m.start(), m.end()) {
                let y: u32 = cap["sy"].parse().unwrap_or(0);
                if (1000..=2999).contains(&y) {
                    covered.push((m.start(), m.end()));
                    if born_year.is_none() {
                        born_year = Some(y);
                    }
                }
            }
        }

        // --- 21z) "fl. Nth century" / "active Nth century" → fl <midpoint> ---
        // Runs before half/plain so it consumes the span first. Without this,
        // "(fl. 13th century)" would emit a bare `c13` token, and the Python
        // deriver — by user instruction — should NOT set floruit from a bare
        // century. We resolve the ambiguity by emitting `fl <year>` directly
        // when the original text qualifies the century with `fl/active/flourished`.
        for cap in self.re_fl_century.captures_iter(text) {
            let m = cap.get(0).unwrap();
            if overlaps(&covered, m.start(), m.end()) { continue; }
            let n: u32 = cap["flccn"].parse().unwrap_or(0);
            if !(1..=25).contains(&n) { continue; }
            let is_bc = cap.name("flcmk").is_some();
            // No half-century modifier: use the plain midpoint.
            let year = century_year(n, is_bc, "");
            covered.push((m.start(), m.end()));
            push_unique(&mut out, format!("fl {}", year));
        }

        // --- 21a) Half/early/mid/late century → fl <signed midpoint> ---
        // Run before the plain century pass so it claims the matched span first.
        for cap in self.re_half_century.captures_iter(text) {
            let m = cap.get(0).unwrap();
            if overlaps(&covered, m.start(), m.end()) { continue; }
            let n: u32 = cap["hcn"].parse().unwrap_or(0);
            if !(1..=25).contains(&n) { continue; }
            let modifier = cap["hmod"].to_ascii_lowercase();
            let is_bc = cap.name("hmk").is_some();
            let year = century_year(n, is_bc, &modifier);
            covered.push((m.start(), m.end()));
            push_unique(&mut out, format!("fl {}", year));
        }
        for cap in self.re_early_late_century.captures_iter(text) {
            let m = cap.get(0).unwrap();
            if overlaps(&covered, m.start(), m.end()) { continue; }
            let n: u32 = cap["elcn"].parse().unwrap_or(0);
            if !(1..=25).contains(&n) { continue; }
            let modifier = cap["elmod"].to_ascii_lowercase();
            let is_bc = cap.name("elmk").is_some();
            let year = century_year(n, is_bc, &modifier);
            covered.push((m.start(), m.end()));
            push_unique(&mut out, format!("fl {}", year));
        }

        // --- 21) Centuries (range form first, then standalone) ---
        let mut century_tokens: Vec<String> = Vec::new();
        for cap in self.re_century_range.captures_iter(text) {
            let m = cap.get(0).unwrap();
            if overlaps(&covered, m.start(), m.end()) { continue; }
            let a: u32 = cap["cra"].parse().unwrap_or(0);
            let b: u32 = cap["crb"].parse().unwrap_or(0);
            if !(1..=25).contains(&a) || !(1..=25).contains(&b) { continue; }
            covered.push((m.start(), m.end()));
            let suffix = if let Some(mk) = cap.name("crmk") {
                format!(" {}", Self::normalize_marker(mk.as_str()))
            } else {
                String::new()
            };
            push_unique(&mut century_tokens, format!("c{}{}", a, suffix));
            push_unique(&mut century_tokens, format!("c{}{}", b, suffix));
        }
        for cap in self.re_century.captures_iter(text) {
            let m = cap.get(0).unwrap();
            if overlaps(&covered, m.start(), m.end()) { continue; }
            let n: u32 = cap["cn"].parse().unwrap_or(0);
            if !(1..=25).contains(&n) { continue; }
            covered.push((m.start(), m.end()));
            let token = if let Some(mk) = cap.name("cmk") {
                format!("c{} {}", n, Self::normalize_marker(mk.as_str()))
            } else {
                format!("c{}", n)
            };
            push_unique(&mut century_tokens, token);
        }

        // --- Assemble output ---
        let mut final_out: Vec<String> = Vec::new();
        if let (Some(b), Some(d)) = (born_year, died_year) {
            if b <= d && sane_year(b) && sane_year(d) {
                push_unique(&mut final_out, format!("{}-{}", b, d));
            }
        }
        if let Some(b) = born_year {
            push_unique(&mut final_out, format!("b {}", b));
        }
        if let Some(d) = died_year {
            push_unique(&mut final_out, format!("d {}", d));
        }
        for tok in out { push_unique(&mut final_out, tok); }
        for tok in century_tokens { push_unique(&mut final_out, tok); }

        // Keep AT MOST ONE range token: when several "YYYY-YYYY" tokens exist, drop
        // every range after the first. (User: "when there are many (XXX-XXX), just
        // keep the first".)
        let mut deduped: Vec<String> = Vec::with_capacity(final_out.len());
        let mut range_kept = false;
        let is_range = |s: &str| -> bool {
            // "1825-1898" or "37-68": digit-hyphen-digit, no leading 'b ', 'd ', etc.
            let bytes = s.as_bytes();
            if bytes.first().map_or(false, |c| !c.is_ascii_digit()) { return false; }
            let mut seen_dash = false;
            for &c in bytes {
                if c == b'-' { seen_dash = true; }
                else if !c.is_ascii_digit() { return false; }
            }
            seen_dash
        };
        for tok in final_out {
            if is_range(&tok) {
                if range_kept { continue; }
                range_kept = true;
            }
            deduped.push(tok);
        }

        if deduped.is_empty() { None } else { Some(deduped.join("|")) }
    }
}

/// Helper to apply a range regex. `name_a`/`name_b` are capture group names.
/// When `require_ordered`, skip if a > b (almost always a false positive).
fn apply_range(
    re: &Regex,
    name_a: &str,
    name_b: &str,
    text: &str,
    covered: &mut Vec<(usize, usize)>,
    out: &mut Vec<String>,
    range_seen: &mut bool,
    require_ordered: bool,
) {
    for cap in re.captures_iter(text) {
        let m = cap.get(0).unwrap();
        if covered.iter().any(|&(s, e)| m.start() < e && s < m.end()) {
            continue;
        }
        let a: u32 = cap[name_a].parse().unwrap_or(0);
        let b: u32 = cap[name_b].parse().unwrap_or(0);
        if !sane_year(a) || !sane_year(b) {
            continue;
        }
        if require_ordered && a > b {
            continue;
        }
        covered.push((m.start(), m.end()));
        push_unique(out, format!("{}-{}", a, b));
        *range_seen = true;
    }
}

fn sane_year(y: u32) -> bool {
    (100..=2999).contains(&y)
}

/// Convert a century number + modifier into a signed midpoint year.
///
/// AD: Nth century covers years (N-1)*100 + 1 .. N*100. Midpoint = (N-1)*100 + 50.
/// BC: Nth century covers years -N*100 .. -((N-1)*100 + 1). Midpoint = -((N-1)*100 + 50).
///
/// "first half"/"early"  picks the earlier-time half of the century.
/// "second half"/"late"  picks the later-time half.
fn century_year(n: u32, is_bc: bool, modifier: &str) -> i32 {
    let base = (n as i32 - 1) * 100;
    if is_bc {
        // For BC, "early/first half" = closer to start of the century in time =
        // more negative (older). E.g. early 4th c. BC ≈ -375.
        let off: i32 = match modifier {
            "first" | "early" => 75,
            "second" | "late" => 25,
            "mid" | "middle" => 50,
            _ => 50,
        };
        -(base + off)
    } else {
        let off: i32 = match modifier {
            "first" | "early" => 25,
            "second" | "late" => 75,
            "mid" | "middle" => 50,
            _ => 50,
        };
        base + off
    }
}

/// True if the byte just before `start` or just after `end` is a digit or '-' —
/// i.e. the matched "YYYY-YYYY" is part of a longer hyphen-chain like an ORCID.
fn in_hyphen_chain(text: &str, start: usize, end: usize) -> bool {
    let bytes = text.as_bytes();
    let prev_is_chain = start > 0 && {
        let c = bytes[start - 1];
        c == b'-' || c.is_ascii_digit()
    };
    let next_is_chain = end < bytes.len() && {
        let c = bytes[end];
        c == b'-' || c.is_ascii_digit()
    };
    prev_is_chain || next_is_chain
}

/// Extend a span backward over a "<digits>/" prefix (with optional whitespace).
/// For "(died 270/269 BC)", calling this on the start of "269" returns the start of "270".
fn extend_back_over_slash(text: &str, start: usize) -> usize {
    let bytes = text.as_bytes();
    let mut i = start;
    while i > 0 && (bytes[i - 1] == b' ' || bytes[i - 1] == b'\t') {
        i -= 1;
    }
    if i == 0 || bytes[i - 1] != b'/' {
        return start;
    }
    i -= 1;
    while i > 0 && (bytes[i - 1] == b' ' || bytes[i - 1] == b'\t') {
        i -= 1;
    }
    let digits_end = i;
    while i > 0 && bytes[i - 1].is_ascii_digit() {
        i -= 1;
    }
    if i == digits_end { start } else { i }
}

fn push_unique(out: &mut Vec<String>, s: String) {
    if !out.iter().any(|x| x == &s) {
        out.push(s);
    }
}

fn ensure_column(conn: &Connection) -> Result<()> {
    let mut stmt = conn.prepare("PRAGMA table_info(individuals)")?;
    let cols: Vec<String> = stmt
        .query_map([], |row| row.get::<_, String>(1))?
        .filter_map(Result::ok)
        .collect();
    if !cols.iter().any(|c| c == "dates_in_description") {
        println!("Adding column individuals.dates_in_description ...");
        conn.execute(
            "ALTER TABLE individuals ADD COLUMN dates_in_description TEXT",
            [],
        )?;
    } else {
        println!("Column dates_in_description already exists");
    }
    Ok(())
}

fn main() -> Result<()> {
    let args = Args::parse();
    let extractor = Extractor::new();
    run_self_tests(&extractor);

    let flags = if args.dry_run {
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX
    } else {
        OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX
    };
    let conn = Connection::open_with_flags(&args.db, flags)
        .with_context(|| format!("opening {}", args.db.display()))?;

    conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA temp_store=MEMORY; PRAGMA cache_size=-200000;")?;

    if !args.dry_run {
        ensure_column(&conn)?;
    }

    let total: i64 = if args.sample > 0 {
        args.sample as i64
    } else {
        conn.query_row(
            "SELECT COUNT(*) FROM individuals WHERE description_en IS NOT NULL AND description_en != ''",
            [],
            |r| r.get(0),
        )?
    };

    let pb = ProgressBar::new(total as u64);
    pb.set_style(
        ProgressStyle::with_template(
            "{bar:40.cyan/blue} {pos:>10}/{len:10} ({eta_precise}) [{per_sec}]  {msg}",
        )
        .unwrap(),
    );

    let limit_clause = if args.sample > 0 {
        format!(" LIMIT {}", args.sample)
    } else {
        String::new()
    };
    let select_sql = format!(
        "SELECT wikidata_id, description_en FROM individuals \
         WHERE description_en IS NOT NULL AND description_en != ''{}",
        limit_clause
    );

    let mut select = conn.prepare(&select_sql)?;
    let mut rows = select.query([])?;

    let mut buffer: Vec<(String, Option<String>)> = Vec::with_capacity(args.batch_size);
    let mut processed: u64 = 0;
    let mut hits: u64 = 0;
    let mut shown_examples: usize = 0;
    let start = Instant::now();

    while let Some(row) = rows.next()? {
        let id: String = row.get(0)?;
        let desc: String = row.get(1)?;
        let extracted = extractor.extract(&desc);
        if extracted.is_some() {
            hits += 1;
            if shown_examples < args.examples {
                println!(
                    "  [{:>2}] {:<12} | {:<60} -> {}",
                    shown_examples + 1,
                    id,
                    truncate(&desc, 60),
                    extracted.as_deref().unwrap()
                );
                shown_examples += 1;
            }
        }
        buffer.push((id, extracted));
        processed += 1;
        pb.inc(1);

        if buffer.len() >= args.batch_size {
            if !args.dry_run {
                flush(&conn, &mut buffer)?;
            } else {
                buffer.clear();
            }
            pb.set_message(format!("hits {}/{}", hits, processed));
        }
    }
    if !buffer.is_empty() {
        if !args.dry_run {
            flush(&conn, &mut buffer)?;
        } else {
            buffer.clear();
        }
    }

    pb.finish_with_message(format!(
        "done — {} hits / {} rows in {:.1}s",
        hits,
        processed,
        start.elapsed().as_secs_f64()
    ));
    println!(
        "summary: {} processed, {} with dates ({:.2}%), elapsed {:.1}s",
        processed,
        hits,
        100.0 * (hits as f64) / (processed.max(1) as f64),
        start.elapsed().as_secs_f64()
    );

    Ok(())
}

fn flush(conn: &Connection, buffer: &mut Vec<(String, Option<String>)>) -> Result<()> {
    let tx = conn.unchecked_transaction()?;
    {
        let mut up = tx.prepare_cached(
            "UPDATE individuals SET dates_in_description = ?1 WHERE wikidata_id = ?2",
        )?;
        for (id, val) in buffer.iter() {
            up.execute(params![val, id])?;
        }
    }
    tx.commit()?;
    buffer.clear();
    Ok(())
}

fn truncate(s: &str, n: usize) -> String {
    if s.chars().count() <= n {
        s.replace('\n', " ")
    } else {
        let t: String = s.chars().take(n.saturating_sub(1)).collect();
        format!("{}…", t.replace('\n', " "))
    }
}

fn run_self_tests(e: &Extractor) {
    let cases: &[(&str, Option<&str>)] = &[
        // --- BC/AD markers ---
        ("Roman consul in 199 BC", Some("199 BC")),
        ("notable Coan of 480 BCE", Some("480 BCE")),
        ("Roman statesman, and consul in AD 10", Some("10 AD")),
        ("Macedonian astronomer around 100 BC", Some("100 BC")),
        ("Greek philosopher (died 270/269 BC)", Some("269 BC")),
        ("b.c.1946", Some("1946 BC")),
        ("B.C. Women's Hospital", None),
        ("Halle a.d.S.", None),

        // --- Plain ranges ---
        ("Dutch maker (1720–1801)", Some("1720-1801")),
        ("(1906-1981)", Some("1906-1981")),
        ("Estonian (1928–1995) and consul in AD 10", Some("10 AD|1928-1995")),

        // --- Loose ranges with text between ---
        ("1879 Cesena - 1965 Cesena | M | IT", Some("1879-1965")),
        ("1343 - before 1376", Some("1343-1376")),
        ("Spanish sculptor, 1702-after 1750", Some("1702-1750")),
        ("(11 Jan 1809 - certain 1885)", Some("1809-1885")),
        ("(est. 1671 - uncertain Apr 1723)", Some("1671-1723")),
        ("(est. 1716 - Apr 1765)", Some("1716-1765")),
        ("Abt 1300 - Aft 1331", Some("1300-1331")),
        ("tenor (Milan 1885 - ? 1946)", Some("1885-1946")),
        ("(est. 1314 - after 1361)", Some("1314-1361")),
        // Loose range rejects reversed years; dash-qualifier-year still emits the
        // trailing year as a death — acceptable noise for likely-typo cases.
        ("Kentucky settler (c. 1763 - c. 1733)", Some("d 1733")),

        // --- "from .. to .." / "between .. and .." ---
        ("Emperor of the Ming dynasty from 1521 to 1567", Some("1521-1567")),
        ("Pope between 1198 and 1216", Some("1198-1216")),

        // --- Decade range ---
        ("Hungarian literary translator (1780s-1840s)", Some("1780-1840")),

        // --- Circa-suffix range ---
        ("1771c-1845c", Some("1771-1845")),

        // --- 2-digit-suffix range ---
        ("Long March (1934-35)", Some("1934-1935")),

        // --- DMY full and asymmetric ranges ---
        ("1 Sep 1858 - 7 Dec 1945", Some("1858-1945")),
        ("(14 Dec 1898 - 28 Jan 1934)", Some("1898-1934")),
        ("20 April 1886 — 28 December 1956", Some("1886-1956")),
        ("1 Oct 1652 - certain 1731", Some("1652-1731")),
        ("2 Aug 1693 Leiden - 18 Sep 1762 Leiden", Some("1693-1762")),

        // --- Open birth ---
        ("Japanese businessman (1947-)", Some("b 1947")),
        ("classical philologist (1851-)", Some("b 1851")),
        ("Austrian pediatrician (1873-?)", Some("b 1873")),
        ("(est. 1623 - uncertain)", Some("b 1623")),
        ("1946-", Some("b 1946")),
        ("Romania, 1920-", Some("b 1920")),
        ("Abt 1345 -", Some("b 1345")),
        ("(13 Apr 1711 - )", Some("b 1711")),
        ("8 Apr 1694 -", Some("b 1694")),

        // --- Open death ---
        ("librettist, poet (-1896)", Some("d 1896")),
        ("- 1466", Some("d 1466")),
        ("- 1208", Some("d 1208")),
        ("- Bef 31 Dec 1478", Some("d 1478")),
        ("- Aft 1422", Some("d 1422")),
        ("- Aug 1464", Some("d 1464")),
        ("- 25 Dec 1447", Some("d 1447")),
        ("- 4 Dec 1501", Some("d 1501")),

        // --- born/died keyword years ---
        ("American sculptor, born 1972", Some("b 1972")),
        ("born 1825; died 1898", Some("1825-1898|b 1825|d 1898")),
        ("Hungarian footballer (b. 1991)", Some("b 1991")),
        ("Scottish doctor (d. 1834)", Some("d 1834")),
        ("died 1798", Some("d 1798")),
        ("Hungarian writer (born: 1945)", Some("b 1945")),
        ("Born 4 February 1816; died 11 May 1864", Some("1816-1864|b 1816|d 1864")),
        ("born April 12, 1879, Vienna; died September 3, 1959, Vienna.", Some("1879-1959|b 1879|d 1959")),
        ("baptized 1623", Some("b 1623")),
        ("buried 1701", Some("d 1701")),

        // --- active / fl. / exhibited ---
        ("Spanish painter, active 1910", Some("fl 1910")),
        ("Spanish painter, active circa 1487", Some("fl 1487")),
        ("Spanish architect, active ca. 1277, died 1296", Some("d 1296|fl 1277")),
        ("acarologist, fl. 1969", Some("fl 1969")),
        ("Person; male; British; fl. c. 1834", Some("fl 1834")),
        ("Spanish painter, exhibited 1884", Some("fl 1884")),
        ("Spanish painter, exhibited 1898", Some("fl 1898")),

        // --- Bare year at start ---
        ("1715", Some("b 1715")),
        ("1837 opera singer", Some("b 1837")),
        ("Abt 1345", Some("b 1345")),

        // --- 2-3 digit paren ranges ---
        ("Roman emperor (37-68)", Some("37-68")),
        ("Byzantine general (850-920)", Some("850-920")),
        ("Greek poet (99-180)", Some("99-180")),
        ("section 37-68 of the manuscript", None),

        // --- Centuries ---
        ("Spanish painter, active 19th-20th centuries", Some("c19|c20")),
        ("mother of Bartolomeo I di Capua (fl. 13th century)", Some("fl 1250")),
        ("French nobleman, fl. 14th century", Some("fl 1350")),
        ("Active 5th century BC", Some("fl -450")),
        ("Greek philosopher of the 4th century BC", Some("c4 BC")),
        ("4th-century BC Greek general", Some("c4 BC")),

        // --- Half-century / early-late refinements (emit precise fl year) ---
        ("Active in Florence in the second half of the 16th century.", Some("fl 1575")),
        ("Sculptor in the first half of the 2nd century", Some("fl 125")),
        ("Engraver of the late 17th century", Some("fl 1675")),
        ("Statesman of the early 4th century BC", Some("fl -375")),
        ("Painter of the mid 18th century", Some("fl 1750")),

        // --- ORCID-style false-positive guard ---
        ("researcher (ORCID 0000-0003-2969-2779)", None),
        ("researcher ORCID ID = 0000-0001-7826-7272", None),

        // --- Academic degree false-positive guard (Ph.D., B.A., M.D., LL.D., Ed.D.) ---
        ("Ph.D. Lund University 1998", None),
        ("B.A. Stanford University 1998", None),
        ("M.D. obtained 1985", None),
        ("Ph.D. Northwestern University 1980", None),

        // --- No-date / negatives ---
        ("(died 1801)", Some("d 1801")),
        ("", None),
    ];
    let mut failures = 0;
    for (input, expect) in cases {
        let got = e.extract(input);
        let got_ref = got.as_deref();
        let ok = got_ref == *expect;
        if !ok {
            failures += 1;
            eprintln!(
                "SELFTEST FAIL: {:?}\n  expected: {:?}\n  got:      {:?}",
                input, expect, got_ref
            );
        }
    }
    if failures > 0 {
        eprintln!("{} selftest failures (continuing)", failures);
    } else {
        println!("selftests: {} cases passed", cases.len());
    }
}
