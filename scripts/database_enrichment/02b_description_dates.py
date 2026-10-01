import os
import re
from multiprocessing import Pool

from tqdm import tqdm

from common import D, Enrichment, ROOT, as_json, open_database, stage
from pydantic_to_duckdb_schema import duck_type

CURRENT_YEAR = 2026
OLDEST_AGE = 110
BATCH = 200_000
CHUNK = 20_000
FIELDS = ("birth_date", "death_date", "floruit_date")
MARK = "Wikidata description"

ENRICHMENT = Enrichment(
    reads=("Individual.entity",),
    writes=("Individual.birth_date[]", "Individual.death_date[]", "Individual.floruit_date[]"),
    rule=f"A year a pattern-matcher read off the individual's one-line English {MARK}, by the regular expressions of database_enrichment/02b_description_dates.py. Two years joined by a dash, 'Italian painter (1712-1782)', are the birth and the death, kept only when they are at most {OLDEST_AGE} years apart. A year the text calls a birth or a death — 'born 1972', 'b. 1991', 'died 1798', '(1947-)', '(-1896)' — is that birth or death, and a year opening the description and followed by a dash, '1939 - present', is a birth. A single year with nothing saying birth or death — 'fl. 1834', 'active 1910', 'consul in 199 BC', 'Pope between 1198 and 1216' (its first year) — is the floruit, and a floruit given as part of a century, 'fl. 13th century', 'second half of the 16th century', is the middle of that part at precision century. A bare century with no fl. or active is not used. Appended as one more entry in each date list, beside the Wikidata property and the other sources.",
    answers=ROOT / "scripts" / "database_enrichment" / "02b_description_dates.py",
)

MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)"
QUALIFIER = r"(?:after|before|aft\.?|bef\.?|circa|ca\.?|c\.?|certain|uncertain|est\.?|estimated|abt\.?|about|probably|approximately)"
DASH = r"[-–—]"
ERA = r"B\.?C\.?E\.?|B\.?C\.?|B\.?C\.E\.?|A\.?D\.?|C\.?E\.?|A\.?C\.?"
BEFORE_CHRIST = r"B\.?C\.?E\.?|B\.?C\.?"
CENTURY_WORD = r"\s*(?:st|nd|rd|th)[\s\-]centur(?:y|ies)"
PARTS = {
    "<M>": MONTH,
    "<Q>": QUALIFIER,
    "<DASH>": DASH,
    "<ERA>": ERA,
    "<BC>": BEFORE_CHRIST,
    "<CENTURY>": CENTURY_WORD,
    "<NL>": r"[^-–—\d\n]{0,25}?",
    "<NR>": r"[^\d\n]{0,25}?",
}


def pattern(text, ignore_case=True):
    for part, value in PARTS.items():
        text = text.replace(part, value)
    return re.compile(text, re.IGNORECASE if ignore_case else 0)


ID_CHAIN = pattern(r"\b\d{1,5}(?:-\d{1,5}){2,}\b", False)
DEGREE = pattern(r"\b[A-Z][a-zA-Z]?\.\s*[A-Z][a-zA-Z]?\.(?:\s*[A-Z][a-zA-Z]?\.)?", False)
MARKER = pattern(r"\b(?:(?P<y1>\d{1,4})\s*[.\-]?\s*(?P<m1><ERA>)|(?P<m2><ERA>)\s*(?P<y2>\d{1,4}))\b")

DATED_RANGES = (
    pattern(r"\b\d{1,2}\s+<M>\s+(?P<a>\d{3,4})<NL><DASH><NR>(?:<Q>\s+)*\d{1,2}\s+<M>\s+(?P<b>\d{3,4})"),
    pattern(r"\b\d{1,2}\s+<M>\s+(?P<a>\d{3,4})\s*<DASH>\s*(?:<Q>\s+)*<M>\s+(?P<b>\d{3,4})\b"),
    pattern(r"\b<M>\s+(?P<a>\d{3,4})\s*<DASH>\s*(?:<Q>\s+)*\d{1,2}\s+<M>\s+(?P<b>\d{3,4})\b"),
    pattern(r"\b\d{1,2}\s+<M>\s+(?P<a>\d{3,4})<NL><DASH>\s*(?:<Q>\s+)*(?P<b>\d{3,4})\b"),
    pattern(r"\b(?P<a>\d{3,4})\s*<DASH><NR>(?:<Q>\s+)*\d{1,2}\s+<M>\s+(?P<b>\d{3,4})\b"),
    pattern(r"\b<M>\s+(?P<a>\d{3,4})\s*<DASH>\s*(?:<Q>\s+)*<M>\s+(?P<b>\d{3,4})\b"),
    pattern(r"\b<M>\s+(?P<a>\d{3,4})\s*<DASH>\s*(?:<Q>\s+)*(?P<b>\d{3,4})\b"),
    pattern(r"\b(?P<a>\d{3,4})\s*<DASH>\s*(?:<Q>\s+)*<M>\s+(?P<b>\d{3,4})\b"),
)
TENURES = (
    pattern(r"\bfrom\s+(?P<a>\d{3,4})\s+to\s+(?P<b>\d{3,4})\b"),
    pattern(r"\bbetween\s+(?P<a>\d{3,4})\s+and\s+(?P<b>\d{3,4})\b"),
)
DECADE_RANGE = pattern(r"\b(?P<a>\d{4})s\s*<DASH>\s*(?P<b>\d{4})s\b", False)
CIRCA_SUFFIX_RANGE = pattern(r"\b(?P<a>\d{4})c\s*<DASH>\s*(?P<b>\d{4})c\b", False)
SHORT_SUFFIX_RANGE = pattern(r"\(\s*(?P<a>\d{4})\s*<DASH>\s*(?P<b>\d{2})\s*\)", False)
PLAIN_RANGE = pattern(r"(?P<a>\d{4})\s*<DASH>\s*(?P<b>\d{4})", False)
LOOSE_RANGE = pattern(r"\b(?P<a>\d{4})[^\d\n]{0,25}?<DASH>[^\d\n]{0,25}?(?P<b>\d{4})\b", False)
PAREN_SHORT_RANGE = pattern(r"\(\s*(?P<a>\d{2,4})\s*<DASH>\s*(?P<b>\d{2,4})\s*\)", False)

OPEN_ENDS = (
    ("b", pattern(r"\(\s*(?:est\.?|circa|ca\.?|c\.|abt\.?|estimated|approximately)?\s*(?P<y>\d{3,4})\s*<DASH>\s*(?:\?|uncertain|unknown|no\s+date)?\s*\)")),
    ("d", pattern(r"\(\s*<DASH>\s*(?P<y>\d{3,4})\s*\)", False)),
    ("b", pattern(r"\b(?P<y>\d{4})\s*<DASH>\s*$", False)),
    ("b", pattern(r"\b\d{1,2}\s+<M>\s+(?P<y>\d{3,4})\s*<DASH>\s*(?:\)|$)")),
    ("d", pattern(r"^\s*<DASH>\s*(?P<y>\d{3,4})\b", False)),
)
DASH_DEATHS = (
    ("d", pattern(r"(?:^|[\s(])<DASH>\s*(?:<Q>\s+)+(?P<y>\d{3,4})\b")),
    ("d", pattern(r"(?:^|[\s(])<DASH>\s*(?:<Q>\s+)*<M>\s+(?P<y>\d{3,4})\b")),
    ("d", pattern(r"(?:^|[\s(])<DASH>\s*(?:<Q>\s+)*\d{1,2}\s+<M>\s+(?P<y>\d{3,4})\b")),
)
FLORUITS = (
    pattern(r"\bactive\b(?:\s+(?:ca\.?|circa|c\.|in))?\s+(?P<y>\d{3,4})(?:s)?\b"),
    pattern(r"\bfl\.?(?:\s+(?:ca\.?|circa|c\.|in))*\s+(?P<y>\d{3,4})(?:s)?\b"),
    pattern(r"\bexhibited\b(?:\s+(?:in|at|ca\.?|circa|c\.))?\s+(?P<y>\d{3,4})\b"),
)
BIRTH_AND_DEATH_WORDS = (
    ("b", pattern(r"\b(?:born|baptized|baptised|b\.|bap\.?|bapt\.?)(?:.{0,40}?)?\b(?P<y>\d{3,4})\b")),
    ("d", pattern(r"\b(?:died|buried|d\.|bur\.?)(?:.{0,40}?)?\b(?P<y>\d{3,4})\b")),
)
YEAR_AT_START = pattern(r"^\s*(?:abt\.?\s+)?(?P<y>\d{3,4})(?:\b|$)")
CENTURY_FLORUITS = (
    pattern(r"\b(?:fl\.?|flourished|active)\s+(?:(?:in|during)\s+)?(?:the\s+)?(?:c\.?\s+|circa\s+|ca\.?\s+)?(?P<n>\d{1,2})<CENTURY>(?:\s+(?P<mk><BC>))?\b"),
    pattern(r"\b(?P<mod>first|second|early|late|mid|middle)\s+(?:half\s+of\s+)?(?:the\s+)?(?P<n>\d{1,2})<CENTURY>(?:\s+(?P<mk><BC>))?\b"),
    pattern(r"\b(?P<mod>early|late|mid)-(?P<n>\d{1,2})<CENTURY>(?:\s+(?P<mk><BC>))?\b"),
)
CENTURY_RANGE = pattern(r"\b(?P<a>\d{1,2})\s*(?:st|nd|rd|th)\s*<DASH>\s*(?P<b>\d{1,2})<CENTURY>(?:\s+(?P<mk><BC>))?\b")
CENTURY = pattern(r"\b(?P<n>\d{1,2})<CENTURY>(?:\s+(?P<mk><BC>))?\b")

TOKEN_BIRTH = re.compile(r"^b (\d+)$")
TOKEN_DEATH = re.compile(r"^d (\d+)$")
TOKEN_LIFE = re.compile(r"^(\d+)(s?)-(\d+)s?$")
TOKEN_TENURE = re.compile(r"^from (\d+)-(\d+)$")
TOKEN_FLORUIT = re.compile(r"^fl (\d+)$")
TOKEN_CENTURY_FLORUIT = re.compile(r"^flc (-?\d+)$")
TOKEN_ERA = re.compile(r"^(\d+) (BCE|BC|AC|AD|CE)$")


def era_of(marker):
    letters = "".join(c for c in marker if c.isalpha()).upper()
    return letters if letters in ("BCE", "BC", "AD", "CE", "AC") else "BC"


def sane(year, low=100):
    return low <= year <= 2999


def century_year(n, before_christ, modifier):
    offset = {"first": 25, "early": 25, "second": 75, "late": 75}.get(modifier, 50)
    if before_christ:
        return -((n - 1) * 100 + 100 - offset)
    return (n - 1) * 100 + offset


def in_hyphen_chain(text, start, end):
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    return any(c.isdigit() or c == "-" for c in before + after)


def back_over_slash(text, start):
    """For '(died 270/269 BC)', the start of '269' moved back to the start of '270'."""
    i = start
    while i > 0 and text[i - 1] in " \t":
        i -= 1
    if i == 0 or text[i - 1] != "/":
        return start
    i -= 1
    while i > 0 and text[i - 1] in " \t":
        i -= 1
    digits_end = i
    while i > 0 and text[i - 1].isdigit():
        i -= 1
    return start if i == digits_end else i


def extract(text):
    """The date tokens a description holds, in the order the extractor trusts them."""
    tokens, centuries, covered = [], [], []
    found = {"b": None, "d": None}
    range_seen = False

    def free(match):
        return not any(match.start() < end and start < match.end() for start, end in covered)

    def add(where, token):
        if token not in where:
            where.append(token)

    def ranges(regex, low=100, label="{a}-{b}", chain_guard=False):
        nonlocal range_seen
        for match in regex.finditer(text):
            if not free(match) or (chain_guard and in_hyphen_chain(text, match.start(), match.end())):
                continue
            a, b = int(match["a"]), int(match["b"])
            if not sane(a, low) or not sane(b, low) or a > b:
                continue
            covered.append(match.span())
            add(tokens, label.format(a=a, b=b))
            range_seen = True

    def single_years(specs):
        for kind, regex in specs:
            for match in regex.finditer(text):
                year = int(match["y"])
                if not free(match) or not sane(year):
                    continue
                covered.append(match.span())
                if found[kind] is None:
                    found[kind] = year

    for regex in (ID_CHAIN, DEGREE):
        covered.extend(match.span() for match in regex.finditer(text))

    for match in MARKER.finditer(text):
        year, marker = (match["y1"], match["m1"]) if match["y1"] else (match["y2"], match["m2"])
        covered.append((back_over_slash(text, match.start()), match.end()))
        add(tokens, f"{int(year)} {era_of(marker)}")

    for regex in DATED_RANGES:
        ranges(regex)
    for regex in TENURES:
        ranges(regex, label="from {a}-{b}")
    ranges(DECADE_RANGE, label="{a}s-{b}s")
    ranges(CIRCA_SUFFIX_RANGE)

    for match in SHORT_SUFFIX_RANGE.finditer(text):
        if not free(match):
            continue
        a = int(match["a"])
        b = a // 100 * 100 + int(match["b"])
        if b < a:
            b += 100
        if sane(a) and sane(b) and b - a <= 200:
            covered.append(match.span())
            add(tokens, f"{a}-{b}")
            range_seen = True

    ranges(PLAIN_RANGE, low=1000, chain_guard=True)
    ranges(LOOSE_RANGE, low=1000)
    ranges(PAREN_SHORT_RANGE, low=1)

    single_years(OPEN_ENDS)
    if not range_seen:
        single_years(DASH_DEATHS)

    for regex in FLORUITS:
        for match in regex.finditer(text):
            year = int(match["y"])
            if free(match) and sane(year):
                covered.append(match.span())
                add(tokens, f"fl {year}")

    single_years(BIRTH_AND_DEATH_WORDS)

    match = YEAR_AT_START.search(text)
    if match and free(match) and sane(int(match["y"]), 1000):
        covered.append(match.span())
        if re.search(DASH, text[match.end():]):
            found["b"] = found["b"] or int(match["y"])
        else:
            add(tokens, f"fl {int(match['y'])}")

    for regex in CENTURY_FLORUITS:
        for match in regex.finditer(text):
            n = int(match["n"])
            if free(match) and 1 <= n <= 25:
                covered.append(match.span())
                modifier = (match.groupdict().get("mod") or "").lower()
                add(tokens, f"flc {century_year(n, match['mk'] is not None, modifier)}")

    for match in CENTURY_RANGE.finditer(text):
        a, b = int(match["a"]), int(match["b"])
        if free(match) and 1 <= a <= 25 and 1 <= b <= 25:
            covered.append(match.span())
            suffix = f" {era_of(match['mk'])}" if match["mk"] else ""
            add(centuries, f"c{a}{suffix}")
            add(centuries, f"c{b}{suffix}")
    for match in CENTURY.finditer(text):
        n = int(match["n"])
        if free(match) and 1 <= n <= 25:
            covered.append(match.span())
            add(centuries, f"c{n} {era_of(match['mk'])}" if match["mk"] else f"c{n}")

    result = []
    born, died = found["b"], found["d"]
    if born is not None and died is not None and born <= died:
        add(result, f"{born}-{died}")
    if born is not None:
        add(result, f"b {born}")
    if died is not None:
        add(result, f"d {died}")
    for token in tokens + centuries:
        add(result, token)

    plain_ranges = [token for token in result if re.fullmatch(r"\d+-\d+", token)]
    return [token for token in result if not re.fullmatch(r"\d+-\d+", token) or token == plain_ranges[0]]


def signed(year, era):
    return -year if era in ("BC", "BCE", "AC") else year


def first(regex, tokens):
    return next((match for match in map(regex.match, tokens) if match), None)


def dates_of(tokens, text):
    """The birth, death and floruit the tokens give, each as (year, precision), and the rule that gave each."""
    dates = {}
    birth, death = first(TOKEN_BIRTH, tokens), first(TOKEN_DEATH, tokens)
    if birth:
        dates["birth_date"] = (int(birth[1]), "year", "stated birth")
    if death:
        dates["death_date"] = (int(death[1]), "year", "stated death")

    life = first(TOKEN_LIFE, tokens)
    if life:
        start, end = int(life[1]), int(life[3])
        precision = "decade" if life[2] else "year"
        if end - start <= OLDEST_AGE:
            dates.setdefault("birth_date", (start, precision, "range"))
            dates.setdefault("death_date", (end, precision, "range"))
        else:
            dates["rejected"] = "range over 110 years"

    eras = [(int(match[1]), match[2]) for match in map(TOKEN_ERA.match, tokens) if match]
    lived = "birth_date" in dates or "death_date" in dates
    if len(eras) == 2 and not lived and re.search(DASH, text):
        start, end = sorted(signed(year, era) for year, era in eras)
        if 0 < end - start <= OLDEST_AGE:
            dates["birth_date"] = (start, "year", "era range")
            dates["death_date"] = (end, "year", "era range")

    floruit = first(TOKEN_FLORUIT, tokens)
    century_floruit = first(TOKEN_CENTURY_FLORUIT, tokens)
    tenure = first(TOKEN_TENURE, tokens)
    if floruit:
        dates["floruit_date"] = (int(floruit[1]), "year", "fl. / active / single year")
    elif century_floruit:
        dates["floruit_date"] = (int(century_floruit[1]), "century", "fl. in a century")
    elif tenure:
        dates["floruit_date"] = (int(tenure[1]), "year", "from ... to / between ... and")
    elif len(eras) == 1 and not lived:
        dates["floruit_date"] = (signed(*eras[0]), "year", "single year with era")

    for field in FIELDS:
        if field in dates and not 0 != dates[field][0] <= CURRENT_YEAR:
            del dates[field]
    return dates


def readable(text):
    """Undoes the mojibake some descriptions carry: 'â\x80\x93' back to '–'."""
    if "â" not in text and "Ã" not in text:
        return text
    for codec in ("latin-1", "cp1252"):
        try:
            return text.encode(codec).decode("utf-8")
        except UnicodeError:
            continue
    return text


def extract_chunk(rows):
    found = []
    for qid, description in rows:
        text = readable(description)
        tokens = extract(text)
        if tokens:
            found.append((qid, dates_of(tokens, text)))
    return len(rows), found


SELF_TESTS = (
    ("Roman consul in 199 BC", ["199 BC"]),
    ("Greek philosopher (died 270/269 BC)", ["269 BC"]),
    ("b.c.1946", ["1946 BC"]),
    ("B.C. Women's Hospital", []),
    ("Dutch maker (1720–1801)", ["1720-1801"]),
    ("Estonian (1928–1995) and consul in AD 10", ["10 AD", "1928-1995"]),
    ("1879 Cesena - 1965 Cesena | M | IT", ["1879-1965"]),
    ("Spanish sculptor, 1702-after 1750", ["1702-1750"]),
    ("(est. 1716 - Apr 1765)", ["1716-1765"]),
    ("Kentucky settler (c. 1763 - c. 1733)", ["d 1733"]),
    ("Emperor of the Ming dynasty from 1521 to 1567", ["from 1521-1567"]),
    ("Hungarian literary translator (1780s-1840s)", ["1780s-1840s"]),
    ("Long March (1934-35)", ["1934-1935"]),
    ("2 Aug 1693 Leiden - 18 Sep 1762 Leiden", ["1693-1762"]),
    ("Japanese businessman (1947-)", ["b 1947"]),
    ("Austrian pediatrician (1873-?)", ["b 1873"]),
    ("librettist, poet (-1896)", ["d 1896"]),
    ("- Bef 31 Dec 1478", ["d 1478"]),
    ("born 1825; died 1898", ["1825-1898", "b 1825", "d 1898"]),
    ("Hungarian footballer (b. 1991)", ["b 1991"]),
    ("Spanish architect, active ca. 1277, died 1296", ["d 1296", "fl 1277"]),
    ("Person; male; British; fl. c. 1834", ["fl 1834"]),
    ("1837 opera singer", ["fl 1837"]),
    ("1939 - present | American | Painter", ["b 1939"]),
    ("Abt 1812 Baltimore - 8 May 1902 Ballston", ["1812-1902", "b 1812", "d 1902"]),
    ("Roman emperor (37-68)", ["37-68"]),
    ("section 37-68 of the manuscript", []),
    ("Spanish painter, active 19th-20th centuries", ["c19", "c20"]),
    ("French nobleman, fl. 14th century", ["flc 1350"]),
    ("Active 5th century BC", ["flc -450"]),
    ("Greek philosopher of the 4th century BC", ["c4 BC"]),
    ("Active in Florence in the second half of the 16th century.", ["flc 1575"]),
    ("Statesman of the early 4th century BC", ["flc -375"]),
    ("researcher (ORCID 0000-0003-2969-2779)", []),
    ("Ph.D. Lund University 1998", []),
)


def self_test():
    failures = [(text, expected, extract(text)) for text, expected in SELF_TESTS if extract(text) != expected]
    for text, expected, got in failures:
        print(f"self-test failed: {text!r} expected {expected} got {got}")
    if failures:
        raise SystemExit(f"{len(failures)} of {len(SELF_TESTS)} self-tests failed")
    print(f"self-tests: {len(SELF_TESTS)} passed\n")


def a_date(year, precision, provenance):
    return as_json(D.Date(iso=None, year=year, precision=precision, field_provenance={"year": provenance, "precision": provenance}))


def remove_previous(connection):
    """Drops the entries a previous run appended, so a rerun does not stack them."""
    for field in FIELDS:
        connection.execute(f"""
            UPDATE individual
            SET {field} = list_filter({field}, d -> coalesce(d.field_provenance['year'].rule, '') NOT ILIKE '%{MARK}%')
            WHERE list_bool_or(list_transform({field}, d -> coalesce(d.field_provenance['year'].rule, '') ILIKE '%{MARK}%'))
        """)


def chunks(reader):
    for batch in reader:
        rows = list(zip(*batch.to_pydict().values()))
        for start in range(0, len(rows), CHUNK):
            yield rows[start:start + CHUNK]


def main():
    ENRICHMENT.announce()
    self_test()
    connection = open_database()
    remove_previous(connection)

    query = "FROM individual SELECT entity.qid, entity.description WHERE regexp_matches(entity.description, '[0-9]')"
    total = connection.execute(f"SELECT count(*) FROM ({query})").fetchone()[0]
    print(f"{total:,} descriptions hold a digit")
    reader = connection.cursor().execute(query).to_arrow_reader(BATCH)

    provenance = ENRICHMENT.provenance()
    rows, rules, rejected = [], {}, 0
    workers = max(1, (os.cpu_count() or 2) - 1)
    with Pool(workers) as pool, tqdm(total=total, desc="descriptions", unit=" rows", mininterval=5) as progress:
        for read, found in pool.imap(extract_chunk, chunks(reader)):
            progress.update(read)
            for qid, dates in found:
                rejected += "rejected" in dates
                entry = {"qid": qid}
                for field in FIELDS:
                    if field in dates:
                        year, precision, rule = dates[field]
                        rules[field, rule] = rules.get((field, rule), 0) + 1
                        entry[field] = a_date(year, precision, provenance)
                    else:
                        entry[field] = None
                if any(entry[field] for field in FIELDS):
                    rows.append(entry)

    print(f"\n{len(rows):,} individuals get a date from their description")
    for (field, rule), count in sorted(rules.items()):
        print(f"   {field:13} {rule:32} {count:>10,}")
    print(f"   {rejected:,} ranges left out, more than {OLDEST_AGE} years apart")

    stage(connection, "described", {"qid": "VARCHAR", **{field: duck_type(D.Date) for field in FIELDS}}, rows)
    for field in FIELDS:
        connection.execute(f"""
            UPDATE individual SET {field} = list_append(individual.{field}, described.{field})
            FROM described WHERE individual.entity.qid = described.qid AND described.{field} IS NOT NULL
        """)
    connection.close()


if __name__ == "__main__":
    main()
