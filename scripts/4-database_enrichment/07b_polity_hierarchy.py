"""Split each Cliopatria meta polity into a row of its own and link parent and child polities period by period."""

import json
from collections import Counter
from dataclasses import dataclass

from tqdm import tqdm

from common import ROOT, Enrichment, as_json, open_database, provenance_column, stage
from pydantic_to_duckdb_schema import columns_of
import datamodel_in_duckdb as D
import raw_file_readers

RELATION_TYPES = {
    "Allegiance of": "allegiance",
    "Alliance between": "alliance",
    "Vassalage of": "vassalage",
    "Personal union": "personal_union",
}

ENRICHMENT = Enrichment(
    reads=("PolityCliopatria.name", "PolityCliopatria.type", "PolityCliopatria.components", "PolityCliopatria.member_of", "PolityCliopatria.from_year", "PolityCliopatria.to_year", "PolityCliopatria.area"),
    writes=("Polity.meta_polities", "Polity.child_polities"),
    rule="Cliopatria writes a meta polity's name in parentheses. The loader dropped the parentheses and so merged a meta polity into the polity of the same name; each territory is matched back to its GeoJSON feature on name, Wikidata item, years and area, and the meta polity's territories become a row of their own. The link's hierarchy_type is 'composite_polity' for a meta polity, or for a RELATION the kind its name opens with. The links are the child's MemberOf, span by span, and the parent's Components where the child's own MemberOf names that parent or nothing — Components lists every descendant, not only the direct children — with consecutive spans joined into one period.",
    answers=ROOT / "data" / "cliopatria_data" / "cliopatria_V2" / "cliopatria_polities_only_v3.geojson",
)


@dataclass(frozen=True)
class Span:
    name: str
    is_meta: bool
    wikidata: str | None
    start_year: int
    end_year: int
    area: int
    type: str
    components: tuple[str, ...]
    member_of: tuple[str, ...]

    @property
    def key(self):
        return (self.name, self.wikidata, self.start_year, self.end_year, self.area)


def names(field):
    return tuple(name.strip() for name in (field or "").split(";") if name.strip())


def bare(name):
    return name[1:-1] if name.startswith("(") and name.endswith(")") else name


def read_spans():
    spans = []
    for properties in tqdm(raw_file_readers.items(raw_file_readers.POLITY, "features.item.properties"), desc="cliopatria features", unit=" features"):
        name = (properties.get("Name") or "").strip()
        if not name:
            continue
        spans.append(Span(
            name=bare(name),
            is_meta=name.startswith("("),
            wikidata=(properties.get("Wikidata") or "").strip() or None,
            start_year=int(properties["FromYear"]),
            end_year=int(properties["ToYear"]),
            area=round(float(properties["Area"])),
            type=properties.get("Type"),
            components=names(properties.get("Components")),
            member_of=names(properties.get("MemberOf")),
        ))
    return spans


def hierarchy_type(span):
    if span.type != "RELATION":
        return "composite_polity"
    return next(kind for opening, kind in RELATION_TYPES.items() if span.name.startswith(opening))


def split_rows(connection, spans):
    """One output row per polity and side: a row's leaf territories keep its id, its meta territories get a new one."""
    left = {True: Counter(), False: Counter()}
    for span in spans:
        left[span.is_meta][span.key] += 1
    kind_of = {span.key: hierarchy_type(span) for span in spans if span.is_meta}

    rows = connection.execute(
        "SELECT cliopatria_id, name, entity.qid, [(t.start_year, t.end_year, t.area) for t in territories] FROM polity ORDER BY cliopatria_id"
    ).fetchall()
    next_id = max(row[0] for row in rows) + 1
    sides, unmatched = [], 0
    for polity_id, name, qid, territories in rows:
        positions = {False: [], True: []}
        kinds = set()
        for position, (start_year, end_year, area) in enumerate(territories, start=1):
            key = (name, qid, start_year, end_year, round(area))
            is_meta = left[False][key] == 0 and left[True][key] > 0
            unmatched += left[False][key] == 0 and left[True][key] == 0
            left[is_meta][key] -= 1
            positions[is_meta].append(position)
            if is_meta:
                kinds.add(kind_of[key])
        for is_meta in (False, True):
            if not positions[is_meta]:
                continue
            own_id = polity_id if not (is_meta and positions[False]) else next_id
            next_id += own_id == next_id
            assert len(kinds) <= 1, f"{name}: meta territories of several kinds {kinds}"
            sides.append({
                "cliopatria_id": polity_id,
                "new_id": own_id,
                "positions": positions[is_meta],
                "hierarchy_type": kinds.pop() if is_meta else None,
            })
    print(f"{len(rows):,} polity rows become {len(sides):,}; {unmatched:,} territories matched no feature and stay base")
    return sides


def rewrite_polity(connection, sides):
    stage(connection, "side", {"cliopatria_id": "BIGINT", "new_id": "BIGINT", "positions": "BIGINT[]", "hierarchy_type": "VARCHAR"}, sides)
    columns = {row[0] for row in connection.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'polity' AND table_catalog = current_database()").fetchall()}
    dropped = [column for column in ("type", "hierarchy_type", "meta_polities", "child_polities") if column in columns]
    exclude = f"EXCLUDE ({', '.join(dropped)})" if dropped else ""
    existence = ""
    if "existence" in columns:
        existence = """, CASE WHEN polity.existence IS NULL THEN NULL ELSE struct_update(polity.existence,
                inception := struct_update(polity.existence.inception, year := list_min([polity.territories[i].start_year for i in side.positions])),
                dissolution := struct_update(polity.existence.dissolution, year := list_max([polity.territories[i].end_year for i in side.positions])))
            END AS existence"""
    connection.execute(f"""
        CREATE OR REPLACE TABLE polity AS
        SELECT polity.* {exclude} REPLACE (
            side.new_id AS cliopatria_id,
            [polity.territories[i] for i in side.positions] AS territories
            {existence}
        )
        FROM polity JOIN side ON polity.cliopatria_id = side.cliopatria_id
        ORDER BY side.new_id
    """)


def merged_periods(years):
    periods = []
    for start_year, end_year in sorted(years):
        if periods and start_year <= periods[-1][1] + 1:
            periods[-1][1] = max(periods[-1][1], end_year)
        else:
            periods.append([start_year, end_year])
    return periods


def links(connection, spans, kind_of):
    polities = connection.execute(
        "SELECT cliopatria_id, name, entity.qid, [(t.start_year, t.end_year, round(t.area)) for t in territories] FROM polity"
    ).fetchall()
    by_key, by_name, name_of = {}, {}, {}
    for polity_id, name, qid, territories in polities:
        name_of[polity_id] = name
        is_meta = kind_of[polity_id] is not None
        by_name.setdefault((name, is_meta), []).append((polity_id, territories))
        for start_year, end_year, area in territories:
            by_key[(name, is_meta, qid, start_year, end_year, area)] = polity_id

    def resolve(raw_name, start_year, end_year):
        candidates = by_name.get((bare(raw_name), raw_name.startswith("(")), [])
        for polity_id, territories in candidates:
            if any(low <= end_year and start_year <= high for low, high, _ in territories):
                return polity_id
        return candidates[0][0] if candidates else None

    own_of = lambda span: by_key[(span.name, span.is_meta, span.wikidata, span.start_year, span.end_year, span.area)]
    stated_parents = {}
    for span in spans:
        stated_parents.setdefault(own_of(span), []).append((span.start_year, span.end_year, {resolve(parent, span.start_year, span.end_year) for parent in span.member_of}))

    def direct(child, parent, start_year, end_year):
        """Components lists every descendant, flattened; a component is a direct child only where its own MemberOf names the parent or names nothing."""
        overlapping = [parents for low, high, parents in stated_parents.get(child, []) if low <= end_year and start_year <= high]
        return any(not parents or parent in parents for parents in overlapping)

    years, unresolved = {}, Counter()
    for span in spans:
        own = own_of(span)
        pairs = [(own, resolve(parent, span.start_year, span.end_year), parent) for parent in span.member_of]
        if span.is_meta:
            for name in span.components:
                child = resolve(name, span.start_year, span.end_year)
                if child is None or direct(child, own, span.start_year, span.end_year):
                    pairs.append((child, own, name))
        for child, parent, raw_name in pairs:
            if child is None or parent is None:
                unresolved[raw_name] += 1
                continue
            years.setdefault((child, parent), set()).add((span.start_year, span.end_year))
    if unresolved:
        print(f"names in MemberOf or Components that match no polity: {dict(unresolved.most_common(10))}")

    meta, children = {}, {}
    for (child, parent), spans_of_pair in years.items():
        for start_year, end_year in merged_periods(spans_of_pair):
            kind = kind_of[parent]
            meta.setdefault(child, []).append(D.PolityLink(cliopatria_id=parent, name=name_of[parent], hierarchy_type=kind, start_year=start_year, end_year=end_year))
            children.setdefault(parent, []).append(D.PolityLink(cliopatria_id=child, name=name_of[child], hierarchy_type=kind, start_year=start_year, end_year=end_year))
    by_start = lambda link: (link.start_year, link.name)
    return [
        {
            "cliopatria_id": polity_id,
            "meta_polities": [as_json(link) for link in sorted(meta.get(polity_id, []), key=by_start)],
            "child_polities": [as_json(link) for link in sorted(children.get(polity_id, []), key=by_start)],
        }
        for polity_id in name_of
    ]


def write_links(connection, rows):
    polity_columns = columns_of(D.Polity)
    stage(connection, "hierarchy", {
        "cliopatria_id": "BIGINT",
        "meta_polities": polity_columns["meta_polities"],
        "child_polities": polity_columns["child_polities"],
    }, rows)
    fields = ("meta_polities", "child_polities")
    written = json.dumps(as_json(ENRICHMENT.provenance())).replace("'", "''")
    marked = ", ".join(f"'{field}': '{written}'::JSON::{provenance_column()}" for field in fields)
    connection.execute(f"""
        CREATE OR REPLACE TABLE polity AS
        SELECT polity.* REPLACE (
            map_concat(polity.field_provenance, MAP {{{marked}}}) AS field_provenance
        ), hierarchy.meta_polities, hierarchy.child_polities
        FROM polity JOIN hierarchy ON polity.cliopatria_id = hierarchy.cliopatria_id
        ORDER BY polity.cliopatria_id
    """)


def report(connection):
    print("\nmeta polities (with children) and base polities (without):")
    print(connection.sql("""SELECT len(child_polities) > 0 AS is_meta, count(*) AS polities, sum(len(territories)) AS territories,
                                   count(*) FILTER (WHERE len(meta_polities) > 0) AS with_a_meta_polity
                            FROM polity GROUP BY 1 ORDER BY 1"""))
    print("links by hierarchy_type:")
    print(connection.sql("SELECT link.hierarchy_type, count(*) AS links FROM (SELECT unnest(child_polities) AS link FROM polity) GROUP BY 1 ORDER BY 2 DESC"))


def main():
    ENRICHMENT.announce()
    spans = read_spans()
    print(f"{len(spans):,} features, {sum(span.is_meta for span in spans):,} of them meta polities\n")
    connection = open_database()
    connection.execute("BEGIN")
    sides = split_rows(connection, spans)
    rewrite_polity(connection, sides)
    kind_of = {side["new_id"]: side["hierarchy_type"] for side in sides}
    rows = links(connection, spans, kind_of)
    childless = [row["cliopatria_id"] for row in rows if kind_of[row["cliopatria_id"]] and not row["child_polities"]]
    assert not childless, f"meta polities without children would be taken for base polities: {childless[:10]}"
    write_links(connection, rows)
    connection.execute("COMMIT")
    report(connection)
    connection.close()


if __name__ == "__main__":
    main()
