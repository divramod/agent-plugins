---
name: halverse
description: Show the user's halverse, the model of their agent system — `/halverse ontology [<term>]` prints the ontology's sections (levels, roles, orders, places, activities with what each farm word stands for, tools) each with its status (in force, draft, open, proposed), or one term with its glossary entry, its place in the ontology, its old word and its command; `/halverse learn [--days <n>]` counts the old words against the farm words in the user's own typed prompts of the last days and names three words to practise. Reads `~/.claude/GLOSSARY.md` and `~/.claude/HALVERSE-ONTOLOGY.md` at call time, stores nothing. Use when the user says /halverse, /hv, "what does <farm word> mean", "show the ontology" or "which farm words do I still not use". `/halverse h` shows help.
---

# halverse

`S=<skill-dir>/scripts`. Read-only: it reads the two source files and the user's transcripts, never writes or sends.

| Call | Short | Does |
|---|---|---|
| `/halverse ontology [<term>]` | `/hv o` | the ontology with each status, or one term |
| `/halverse learn [--days <n>]` | `/hv l` | old words against farm words in the user's prompts (default 7 days) |
| `/halverse h` | `/hv h` | print this table and stop |

A bare `/halverse` prints this table and stops.

## 1. ontology

Run `python3 $S/halverse.py ontology [<term>]` (`--json` for data). Explain from its output only, never from memory:

- Without a term: the sections as the script printed them. Say what is in force (defined in the glossary) and what is
  only a draft, open or proposed.
- With a term: its glossary entry, its place in the ontology, its old word and the command it stands for.

Exit 1: the term is unknown, say so and offer the closest terms it printed. Exit 2: a source file is missing, name it.

## 2. learn

Run `python3 $S/halverse.py learn [--days <n>]`, print its table unchanged, then give one tip of your own wording on
each of the three words the script named under "practise". You count nothing yourself.
