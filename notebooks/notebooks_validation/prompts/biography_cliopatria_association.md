# Prompt: biography_cliopatria_association

Prompt given to each Claude Code agent (`claude -p`, claude-opus-5-5, run in parallel by
03_cliopatria_association.ipynb) that associates the places extracted from the biographies
(biography_life_stage_extraction.md, 02_extract_places_from_biographies.ipynb) with existing Cliopatria polities. Only `{CANDIDATES}` changes between agents.
For each stage, the candidates are the Cliopatria polities whose territory contains a point of the extracted place
during the stage years given by the biography (over the life years the biography gives for the other stages when the stage
has no years, over all years when the biography gives none). Cultura is never shown to the agent.

---

You are associating places extracted from historians' biographies with historical polities of the Cliopatria dataset, for a validation benchmark (Nature Scientific Data paper). Do not open any file and do not use the web: everything you need is below.

Each individual's life is split into three stages: pre_active (birth to the start of the active life), active (the active life: works, offices, professional activity) and post_active (end of the active life to death). For each individual and stage you are given the place extracted from the biography (as written in the text and in English), the years of the stage according to the biography (null when unknown), the supporting extracts, and the candidate Cliopatria polities: each with its name, its years of existence in Cliopatria, the polities it belongs to ("member_of") and the extracted point(s) its territory contains.

For each stage, choose the polity or polities that governed the place during the stage years:
- choose only among the candidates of that stage, and copy their names exactly;
- one polity per distinct place of the stage (a stage with several places may get several polities);
- for a place, prefer the smallest polity, the most specific one in the member_of hierarchy, that held the place during most of the stage years;
- use the extracts and your historical knowledge to decide which candidate fits the place at the time (for example, a city of a contested border region);
- if no candidate fits, give an empty list.

Candidates (JSON, QID -> stage -> data):

{CANDIDATES}

Reply with only one JSON object, no text around it: QID -> {"pre_active": {...}, "active": {...}, "post_active": {...}}, every QID and stage of the input, each stage object having:
- "polities": list of chosen candidate names, most important first
- "confidence": "high" | "medium" | "low"
- "reasoning": one short sentence
