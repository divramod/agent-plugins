---
name: halverse
description: Show the user's halverse, the model of their agent system — `/halverse ontology [<term>]` prints the ontology's sections (levels, roles, orders, places, activities with what each farm word stands for, tools) each with its status (in force, draft, open, proposed), or one term with its glossary entry, its place in the ontology, its old word and its command; `/halverse learn [--days <n>]` counts the old words against the farm words in the user's own typed prompts of the last days and names three words to practise. `/halverse voiceink [status|restore]` adds the glossary's, the ontology's and DICTATION.md's words to VoiceInk (replacements and vocabulary) through `hal2-cli-voiceink`, reports what it added, shows the difference without writing, or puts the newest backup back. `ontology` and `learn` read `~/.claude/GLOSSARY.md` and `~/.claude/HALVERSE-ONTOLOGY.md` at call time and store nothing. Use when the user says /halverse, /hv, "sync VoiceInk", "add the words to VoiceInk", "/hv voiceink", "what does <farm word> mean", "show the ontology" or "which farm words do I still not use". `/halverse h` shows help.
---

# halverse

`S=<skill-dir>/scripts`. `ontology` and `learn` are read-only: they read the two source files and the user's transcripts, never write or send. Only `voiceink` writes, and only through `hal2-cli-voiceink` into VoiceInk's store, after a backup.

| Call | Short | Does |
|---|---|---|
| `/halverse ontology [<term>]` | `/hv o` | the ontology with each status, or one term |
| `/halverse learn [--days <n>]` | `/hv l` | old words against farm words in the user's prompts (default 7 days) |
| `/halverse voiceink` | `/hv voiceink` | sync the words into VoiceInk and report what it added |
| `/halverse voiceink status` | `/hv voiceink status` | the difference to VoiceInk, writes nothing |
| `/halverse voiceink restore` | `/hv voiceink restore` | put the newest backup of VoiceInk's store back |
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
- Exit codes (the script's message says what to do; relay it): 2 the CLI is not installed (the message gives
  `cargo install --path apps/hal2-cli-voiceink` from the hal2 repository's `code/rust`) or one of the three source
  files cannot be read (the message names it), 3 no store (VoiceInk not
  installed, never opened or not a Mac), 4 an unknown schema (VoiceInk was updated; it names the verified versions;
  nothing was written), 5 the store cannot be used now (busy: call again in a moment, a sync never needs VoiceInk quit; a `restore`
  while VoiceInk runs: the user quits VoiceInk and calls `restore` again), 6 the write failed (the message says
  whether anything was written and whether the backup was put back), 7 no backup to restore. Any other code: print the message.
