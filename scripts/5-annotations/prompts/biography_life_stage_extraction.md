# Prompt: biography_life_stage_extraction

Prompt given to each Claude Code agent (claude-opus-5-5, general-purpose subagents run in parallel) that extracts the
pre-active, active and post-active places of the benchmark individuals from their biography
(scripts/5-annotations/building_scripts/benchmark300_texts.py). Only `{QIDS}` and `{N}` change between agents.
The stages follow the Cultura life stages of notebooks_polity/01_life_stage_polities_export.py: pre-active life
(birth to start of active life), active life (start to end of active life) and post-active life (end of active life
to death). The places are then mapped to Cliopatria polities over the Cultura stage years and compared with Cultura
by biography_example_validation.py --benchmark 300. It replaces biography_polity_extraction.md (early, active, late).

---

You are extracting structured data from historians' biographies for a validation benchmark (Nature Scientific Data paper, repo /Users/charlesdedampierre/Desktop/Rsearch Folder/cultura/cultura_database). Work only from the biography texts; do NOT open any database, parquet, TSV or Cultura file (the comparison must be blind). Do not use the web.

Your individuals (QIDs): {QIDS}
Each text is at scripts/5-annotations/benchmark/benchmark300/texts/{QID}.txt (header gives the name, dictionary and URL). Some are very long (Stanford Encyclopedia of Philosophy entries): read the opening and the life/biography section (use grep for place names, "born", "died", "Life", etc.) rather than the whole entry.

The life of each individual is split into three stages around the active life. The active life runs from the first to the last work, office or professional activity the individual is known for (first publication, first artwork, first post, first reign or command... up to the last one).
- pre_active: from birth to the start of the active life. Where the individual was born, grew up, was educated and trained, before the first work or office.
- active: from the start to the end of the active life. Where the individual worked, held offices, created or published their works (several places allowed).
- post_active: from the end of the active life to death. Where the individual lived after the last work or office (retirement, exile, last residence) and where they died. If the individual was active until death, give the place where they died.

For each individual and each stage, write the most granular place the biography gives (a city, a region...). If the text says nothing usable for a stage, set that stage to null. Do not use outside knowledge to invent places the text does not mention; you may use your knowledge only to give coordinates.

Output format: the format of scripts/5-annotations/biography_examples/claude_extraction.json (read it first as the reference), with the stage keys renamed. Per QID: {"dictionary": <dictionary name from the header>, "pre_active": {...}|null, "active": {...}|null, "post_active": {...}|null}. Each stage object has:
- "place": the place(s) in English, separated by "; "
- "written": the place as written in the text (short, original language)
- "written_en": English translation of "written" (identical if the text is English)
- "verbatim": list of word-for-word extracts from the text supporting the answer. They MUST be exact substrings of the text file (copy-paste, same spelling, accents and spacing); keep each under ~300 characters.
- "verbatim_en": same list translated to English, same length and order (identical if English)
- "confidence": "high" | "medium" | "low"
- "reasoning": one short sentence
- "points": list of [place name, longitude, latitude] for each place (decimal degrees, your best estimate of the place's location)

Write the result as one JSON object (QID -> entry) to scripts/5-annotations/benchmark/benchmark300/extraction_life_stages/agent_{N}.json (ensure_ascii false, indent 2). Then check it with Python (.venv/bin/python): valid JSON, all your QIDs present, keys pre_active / active / post_active, verbatim and verbatim_en same length, and every verbatim string found in its text file (report and fix any that are not). Reply with a short summary: how many stages filled vs null, and any verbatim you could not match.
