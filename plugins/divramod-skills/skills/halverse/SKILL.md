---
name: halverse
description: Show and maintain the user's halverse, the model of their agent system — `/halverse add [<term>]`, `/halverse change <term>` and `/halverse retire <term>` check a term against every term there is, word it in English, German, Dutch and European Portuguese, propose the exact lines in the Q form and, only on the user's yes, write it into the glossary, the ontology, their companion files, DICTATION.md and VoiceInk at once; `/halverse short <short> = <word>` sets a short form (`--farm` a farm's, `--spoken` one VoiceInk hears); `/halverse ontology [<term>]` prints the ontology's sections with their status, or one term with its glossary entry, its old word and its command; `/halverse check` counts the files' errors and notes and lists what is untranslated per language; `/halverse learn [--days <n>]` counts the old words against the farm words in the user's own typed prompts and names three to practise; `/halverse voiceink [status|restore|prompt|export]` syncs the words into VoiceInk, shows the difference, puts a backup back, prints the correction prompt for dictation or writes VoiceInk's import file. Every file is read and written only through `hal2-cli-halverse` and `hal2-cli-voiceink`. Use when the user says /halverse, /hv, "add the term", "a new farm word", "rename the term", "retire the word", "a short form for", "sync VoiceInk", "check the glossary", "what does <farm word> mean", "show the ontology" or "which farm words do I still not use". `/halverse h` shows help.
---

# halverse

`S=<skill-dir>/scripts`. `ontology`, `check` and `learn` are read-only: they read the user's files only through `hal2-cli-halverse` (the one parser; the glossary, the ontology and DICTATION.md with their German, Dutch and Portuguese companions) and the transcripts, never write or send. `add`, `change`, `retire` and `short` write those nine files, and only through `hal2-cli-halverse`'s writer (all files of a term or none, after a backup); `voiceink` writes VoiceInk's store, and only through `hal2-cli-voiceink`, after a backup. You never edit one of the nine files yourself, with no tool and for no reason, also not to repair one.

| Call | Short | Does |
|---|---|---|
| `/halverse ontology [<term>]` | `/hv o` | the ontology with each status, or one term |
| `/halverse check` | `/hv check` | errors, notes and what is untranslated per language in the halverse files |
| `/halverse learn [--days <n>]` | `/hv l` | old words against farm words in the user's prompts (default 7 days) |
| `/halverse add [<term> [= <what it stands for>]]` | `/hv add` | a new term: checked, worded in four languages, proposed, written on the user's yes |
| `/halverse change <term>` | `/hv change` | the same for a term that exists |
| `/halverse retire <term> [by <term>]` | `/hv retire` | a term leaves the files and joins its successor's `_Avoid_` |
| `/halverse short [<short> = <word>]` | `/hv short` | the short forms listed, or one set at once (`--farm`, `--spoken`, `rm <short>`) |
| `/halverse voiceink` | `/hv voiceink` | sync the words into VoiceInk and report what it added |
| `/halverse voiceink status` | `/hv voiceink status` | the difference to VoiceInk, writes nothing |
| `/halverse voiceink restore` | `/hv voiceink restore` | put the newest backup of VoiceInk's store back |
| `/halverse voiceink prompt` | `/hv voiceink prompt` | the correction prompt for dictation |
| `/halverse voiceink export` | `/hv voiceink export` | VoiceInk's import file, without opening its store |
| `/halverse h` | `/hv h` | print this table and stop |

A bare `/halverse` prints this table and stops.

## 1. ontology

Run `python3 $S/halverse.py ontology [<term>]` (`--json` for data). Explain from its output only, never from memory:

- Without a term: the sections as the script printed them. Say what is in force (defined in the glossary) and what is
  only a draft, open or proposed.
- With a term: its glossary entry, its place in the ontology, its old word and the command it stands for.

Exit 1: the term is unknown, say so and offer the closest terms it printed. Exit 2: `hal2-cli-halverse` is not installed
(the message gives `cargo install --path apps/hal2-cli-halverse` from the hal2 repository's `code/rust`) or one of the files
cannot be read (the message names it; the CLI reads the three English files, DICTATION.md too), say so and stop.

## 2. learn

Run `python3 $S/halverse.py learn [--days <n>]`, print its table unchanged, then give one tip of your own wording on
each of the three words the script named under "practise". You count nothing yourself. Without the CLI or with a file it
cannot read the table still comes, with one line saying the pairs were not checked against the files: relay it.

## 3. voiceink

Run `python3 $S/halverse.py voiceink [status | restore [<backup>|--list] | --dry-run]` and relay its report unchanged
(`--json` for the CLI's data). The script makes one call of `hal2-cli-voiceink <sync|status|restore> --json`; you count
and decide nothing. Without an action it syncs: it writes at once (the user asked for it, no question first), after a
backup, and never deletes what the user added in VoiceInk by hand. The report says the vocabulary words and
replacements added, how many were there already, what was refused and why, and where the backup is.

- `status` and `--dry-run` write nothing. `restore` puts the newest backup back, `restore --list` names them; a
  restore works only while VoiceInk is quit (the user quits it, never you) and keeps the store as it was in a file it names.
- After a sync, say in one line: the vocabulary takes effect in dictation only with VoiceInk's AI enhancement on (the
  guide for it is field 07's); if VoiceInk does not show the new words, quit and reopen it. After a `restore`: open VoiceInk again.
- `voiceink prompt` (one call of `hal2-cli-halverse prompt`) prints the correction prompt: the measured wording, then
  every term with what the speech model writes for it. Give the text between the two lines of dashes in one code
  block, unchanged and whole; it is for the custom prompt of VoiceInk's AI enhancement (where VoiceInk keeps that
  prompt you have not seen: say so). Nothing is written.
- `voiceink export [--out <file>]` (one call of `hal2-cli-voiceink export`) writes VoiceInk's import file and opens no
  store: the way in for a VoiceInk whose store the sync does not know (exit 4). Say the file's path as the script
  printed it; the user imports it with VoiceInk's own "Import Dictionary".
- Exit codes (the script's message says what to do; relay it): 2 the CLI is not installed (the message gives
  `cargo install --path apps/hal2-cli-voiceink` from the hal2 repository's `code/rust`), one of the three source
  files cannot be read (the message names it) or the import file cannot be written, 3 no store (VoiceInk not
  installed, never opened or not a Mac), 4 an unknown schema (VoiceInk was updated; it names the verified versions;
  nothing was written; `/hv voiceink export` is the way in until then), 5 the store cannot be used now (busy: call
  again in a moment, a sync never needs VoiceInk quit; a `restore` while VoiceInk runs: the user quits VoiceInk and
  calls `restore` again), 6 the write failed (the message says whether anything was written and whether the backup
  was put back), 7 no backup to restore. Any other code: print the message.

## 4. check

Run `python3 $S/halverse.py check` (`--json` for the CLI's data and the untranslated terms) and relay its report
unchanged: the counts of errors and notes, at most 25 lines of each (file, line, message, rule; a companion's problem
names the companion's file), and per language the terms whose word, description or ontology row is still the English
one. You count and judge nothing; to say what to do, name the rule of a problem. Exit 0: no error (notes never fail),
1: at least one error, 2: `hal2-cli-halverse` is not installed or a file cannot be read (named): say so and stop.

## 5. add, change

The user's rule: the skill proposes, and writes only what the user confirmed. You word the term in English, German,
Dutch and European Portuguese and judge its fit; the script makes every call and code does everything else. The six
steps below run in this order, none is skipped, none is swapped, and there is exactly one question (step 4). `/hv add`
without a term takes the term the conversation settled. For `change`, read `change` wherever a command says `add`.

**Step 1: the check, then the fit said in words.** Before you word or propose anything:

- `add`: run `python3 $S/halverse.py add check <word>...` with the term and every synonym (a phrase in quotes). It
  compares each word with every term, synonym, `_Avoid_` word, word of the other languages, ontology term, short
  form and dictation word of the files and of the current repository's own `GLOSSARY.md`, and prints `free` or each
  clash with its file and line.
- `change`: run `python3 $S/halverse.py change show <term>` (the term as the files have it, as data: its entry, its
  four languages, its places in the ontology, its short forms), and `change check <word>...` for every word the
  change brings in (a clash at the term's own entry is its own word, no clash).

Then tell the user the fit, in words, every point, before any proposal:

1. free, or each clash as the script printed it, and what it means for this term;
2. the term's category (a level, a role, an order, a place, an activity, a tool, or none of them) and its place in
   the ontology: the section, the table and the status it gets, or that the ontology does not name it (then it gets
   a glossary entry only);
3. the farm picture: what on a farm the word is, and whether the picture holds beside its neighbours;
4. a synonym of a term that exists (then this is a `change` of that term, which gains a head word: say so and go
   on as `change`) or a new term;
5. a likely mishearing: when the word reached you by dictation and reads like a term that exists misheard (a heard
   form of DICTATION.md, a word that sounds like one), name the term you think was meant;
6. what speaks against it (a clash that stays, a picture that does not hold, a word close to another in sound or
   hard to dictate), or that nothing does.

A word that already heads a glossary entry cannot be added: say so and go on as `change`, or stop.

**Step 2: the document.** One JSON document, written to a file outside every repository (a temporary folder), with
your wording in the four languages. A text is one paragraph (the writer wraps it); the document holds no heading, no
table row and no `|`.

```json
{
  "terms": ["berth", "slip"],
  "section": "Harbours",
  "definition": "A numbered second mooring of a ship.",
  "avoid": "slot (the old word), pane",
  "languages": {
    "de": {"word": "Liegeplatz", "description": "...", "section": "Häfen"},
    "nl": {"word": "ligplaats", "description": "...", "section": "Havens"},
    "pt-PT": {"word": "cais", "description": "...", "section": "Portos"}
  },
  "ontology": {"section": "Places", "term": "slip", "cells": ["a berth"], "status": "in force",
    "languages": {"de": {"heading": "Orte (in Kraft)", "cells": ["ein Liegeplatz", "in Kraft"]},
                  "nl": {"cells": ["een ligplaats", "van kracht"]}, "pt-PT": {"cells": ["um cais", "em vigor"]}}},
  "short_forms": [{"short": "bt", "spoken": false}],
  "dictation": {"heard_as": ["birth"], "note": "..."}
}
```

- The head: `terms` (the term, then its synonyms; a phrase term in its own double quotes, `"\"tell the farm\""`),
  `section` (the glossary section's title as the English file writes it), `definition`, `avoid` (the `_Avoid_`
  line's text).
- The German word is `languages.de.word`, written as the glossary's `_de_:` line, its one home; the Dutch and the
  Portuguese word are `languages.nl.word` and `languages.pt-PT.word`. The three descriptions are
  `languages.<language>.description`. `languages.<language>.section` is the section's title in that language, used
  only where the companion has no entry of that section yet: take it from a term of that section that is translated
  there (`change show <a term of it>`), else word it.
- The wording's sources, in the hal2 repository (`~/a/hal2`): a farm word's Dutch and Portuguese word follows
  `research/0075-halverse-plugin-the-voiceink-dictionary-store-and-the-plugin/farm-words-nl-pt.md` (the list the
  user approved; where it and the files differ, the files are right); every other term follows
  `docs/i18n/glossary.toml` (one fixed word per term and language, `keep = true` stays English, the denied words)
  with the style guides beside it (`de.md`, `nl.md`, `pt-PT.md`). A name of hal2's own that neither lists (a
  command, a file) keeps its English word in every language. Portuguese is European Portuguese.
- The ontology's place, where the fit named one: `ontology.section` (its title without the parenthesis), `term` (the
  head word the place stands under), `cells` (the English row's cells after the first, without the `Status`
  column's), `status`, and per language `cells` (every cell after the first, the status word in that language among
  them) and `heading` (the section's heading in that language with its parenthesis, used where the companion lacks
  the section). Of a row several terms share: this term's comma part of a cell that pairs, the other cells as they
  stand. No place: leave `ontology` out.
- `short_forms` and `dictation.heard_as` hold only a short form or a heard form the user named (`spoken: true` for a
  short form that is also spoken; never one of one letter).
- A `change` gives `terms` (its first word names the entry) and only what changes; an empty `avoid` or word takes
  that line away.
- Once worded, run `add check` again with the German, the Dutch and the Portuguese word where it is not the English
  one, and say a clash it names before the proposal.

**Step 3: the dry run.** Run `python3 $S/halverse.py add propose --from <file>`. It writes nothing and opens no
store; it prints, per file, the exact lines that would be written (with the lines that give way) and a proposal
number. Exit 3: the CLI refuses the document; the script names the field, the file and the line: correct the document
and run step 3 again, and ask the user nothing about it. "nothing to write": say so and stop.

**Step 4: the one question.** The fit is said; now give the script's lines per file in one code block, every file,
unchanged, nothing summarised. Then end the reply with one question in the user's Q form (`~/AGENTS.md`, "Questions
to the user"), as plain text after the lines and never in a question dialog, which would hide them:

```
Q<n>: Write the term "<term>" into the halverse files as shown above (<count> files; VoiceInk gets its English and
German word)? <one sentence: what the fit said, and what speaks against it if anything does>
  a) (Recommended) Write as shown: the lines above go into the <count> files after a backup, VoiceInk is synced
  b) Change something: say what (a word, a description, the place); I show the new lines and ask again
  c) Do not write: no file changes
```

Exactly these three options, the recommended one first: that is "write as shown", unless what speaks against the term
is weighty enough that you would not write it; then "do not write" stands first and is the recommended one. Ask
nothing else in this flow: what you might ask (which section, which German word) you decide, say in the fit, and the
user changes with b).

**Step 5: one writing call, only on the user's yes.** Only when the user's answer chooses "write as shown" (its
letter, "yes", "write"): run `python3 $S/halverse.py add write --from <file> --confirmed <proposal number>`, with
the same file, unchanged, and the number step 3 printed. One call. Never without that answer: not on silence, not on
an answer about something else, not because the term seems obvious, and never with a number you made up. On "change
something": change the document, run step 3 again (it prints a new number), ask again with a new Q number. On "do not
write": say that nothing was written, and stop. Exit 6: the script made no call, because the number is missing or the
document is no longer the proposal's: go back to step 3.

**Step 6: the report.** Relay the script's report unchanged: every file changed with its lines, the backup of the
nine files, the check's counts, what VoiceInk got or why not (the files stand whatever VoiceInk says; `/hv voiceink`
repeats the sync), and its last line, that sessions already running read the glossary at their start and learn the
term after a clear. A line starting `WARNING` (the written lines differ from the proposal) comes first in your reply.
Exit 3, 4 or 5: relay the script's text, which names the file and the line that refused and what was put back, left
or recovered. 4 `locked`: call step 5 again in a moment; 4 `changed-meanwhile`: step 3 again and ask again; 5: tell
the user and write nothing more yourself.

## 6. retire

`/hv retire <term> [by <term>]`: the word leaves its head line (the whole entry when it was its only head) in the
glossary and the companions, its ontology rows and its DICTATION.md row go, and with a successor it joins that entry's
`_Avoid_` line and its short forms then stand for the successor. The same order as section 5, one question:

1. `python3 $S/halverse.py retire show <term>` (exit 1: no such term, say so and stop). No successor named: choose
   the entry that replaces the word (the term the user now says instead, its entry's other head), or none where
   nothing replaces it; the question says which you took and why.
2. `python3 $S/halverse.py retire propose <term> [--by <successor>]`: the dry run, the lines per file and the proposal
   number. Without a successor the CLI refuses while a short form still stands for the term; the script says so.
3. The lines in a code block, then the one question in the Q form, three options, the recommended first: write as
   shown (naming the successor, or that there is none), change something (another successor, or none), do not write.
4. Only on the user's yes: `python3 $S/halverse.py retire write <term> [--by <successor>] --confirmed <proposal
   number>`, with the same words as the proposal.
5. Relay the report unchanged, with its note that VoiceInk keeps the word and its replacements (a sync never deletes;
   the user removes them in VoiceInk by hand if they must go).

## 7. short

A short form is what the user types instead of a word ("wt" for worktree); agents read it as its word and never
write it back. It is written at once, without a question: the user asked for exactly this, and a backup is made.

- `/hv short`: `python3 $S/halverse.py short` lists the short forms, the words' and the farms'.
- `/hv short <short> = <word>`: `python3 $S/halverse.py short set <short> <word>`. The word must be a term of the
  glossary.
- `/hv short --farm <short> = <folder name>`: `... short set <short> <folder name> --farm`, a farm's short form (the
  farm is the project folder's name; it needs no glossary entry).
- `/hv short --spoken <short> = <word>`: `... short set <short> <word> --spoken`, also a heard form in DICTATION.md,
  so VoiceInk writes the word when the user says the short form. Never for one letter: the CLI refuses it.
- `/hv short rm <short>`: `python3 $S/halverse.py short rm <short>`.

Relay the report unchanged (the lines written, the backup, what VoiceInk got). Exit 3: the CLI's check refuses the
short form (it is a term itself, it stands in the other table, it cannot be spoken); say the script's reason, and
only then ask one question in the Q form with three options that fit the refusal, the recommended first (another
short form you name, the one that stands replaced, nothing changed). Exit 4 `locked`: call again in a moment.
