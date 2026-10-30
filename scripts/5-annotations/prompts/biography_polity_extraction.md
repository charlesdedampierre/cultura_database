# Prompt: biography_polity_extraction

Prompt given to each of the five Claude Code agents (claude-opus-5-5, general-purpose subagents, run in parallel on
2026-10-30) that extracted the life-stage places of the 50 benchmark individuals
(scripts/5-annotations/building_scripts/benchmark50_texts.py). Only `{QIDS}` and `{N}` changed between agents.
The reference format file, biography_examples/claude_extraction.json, holds the 13 examples extracted by hand in the
main session. The places are then mapped to Cliopatria polities and compared with Cultura by
biography_example_validation.py --benchmark50.

---

You are extracting structured data from historians' biographies for a validation benchmark (Nature Scientific Data paper, repo /Users/charlesdedampierre/Desktop/Rsearch Folder/cultura/cultura_database). Work only from the biography texts; do NOT open any database, parquet, TSV or Cultura file (the comparison must be blind). Do not use the web.

Your individuals (QIDs): {QIDS}
Each text is at scripts/5-annotations/benchmark/benchmark50/texts/{QID}.txt (header gives the name, dictionary and URL). Some are very long (Stanford Encyclopedia of Philosophy entries): read the opening and the life/biography section (use grep for place names, "born", "died", "Life", etc.) rather than the whole entry.

For each individual and each life stage, write the most granular place the biography gives (a city, a region...):
- early: where the individual was born and grew up, before the active life
- active: where the individual worked during the active life (several places allowed)
- late: where the individual lived at the end of life and died
If the text says nothing usable for a stage, set that stage to null. Do not use outside knowledge to invent places the text does not mention; you may use your knowledge only to give coordinates.

Output format: exactly the format of scripts/5-annotations/biography_examples/claude_extraction.json (read it first as the reference). Per QID: {"dictionary": <dictionary name from the header>, "early": {...}|null, "active": {...}|null, "late": {...}|null}. Each stage object has:
- "place": the place(s) in English, separated by "; "
- "written": the place as written in the text (short, original language)
- "written_en": English translation of "written" (identical if the text is English)
- "verbatim": list of word-for-word extracts from the text supporting the answer. They MUST be exact substrings of the text file (copy-paste, same spelling, accents and spacing); keep each under ~300 characters.
- "verbatim_en": same list translated to English, same length and order (identical if English)
- "confidence": "high" | "medium" | "low"
- "reasoning": one short sentence
- "points": list of [place name, longitude, latitude] for each place (decimal degrees, your best estimate of the place's location)

Write the result as one JSON object (QID -> entry) to scripts/5-annotations/benchmark/benchmark50/extraction/agent_{N}.json (ensure_ascii false, indent 2). Then check it with Python (.venv/bin/python): valid JSON, all your QIDs present, verbatim and verbatim_en same length, and every verbatim string found in its text file (report and fix any that are not). Reply with a short summary: how many stages filled vs null, and any verbatim you could not match.
