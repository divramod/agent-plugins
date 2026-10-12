---
name: adr
description: Decision records (ADRs) of a repository that keeps them in hal2's record format (`.adr/<slug>.md` with a front matter envelope) — decide whether a decision of the current work is promoted to a record (the decision ladder — question, plan decision, decision record), then write it with `hal2-cli-records` — a new record (`add`) or a dated amendment of the record it changes, link it both ways with the plan's ledger entry, regenerate the index and INTENT.md's decision log and run the check; also find what binds a file (`for <path>`), search, list and show records. Use when the user says /adr, "write an ADR", "record this decision", "is there an ADR for", "which rules apply to this file", or when a plan decision outlives its plan. `/adr h` shows help.
---

# adr

A decision record is the full form of a lasting decision: `.adr/<slug>.md` with the front matter envelope and the
sections Context, Decision, Consequences, Confirmation, amendments appended. The format is hal2's decision record
`.adr/record-formats.md`; **`hal2-cli-records` does every deterministic part** (the template, the check, the index, the
generated decision log, the lookups). Your job is the judgment: whether a decision is promoted at all, whether it is
a new record or an amendment, and the record's words.

`A=${HAL2_CLI_RECORDS:-hal2-cli-records}`: the binary is `$HAL2_CLI_RECORDS` when set (a hal2 worktree whose
branch is ahead of the installed binary points it at its own build, `code/rust/target/debug/hal2-cli-records` after
`cargo build -p hal2-cli-records`), else `hal2-cli-records` on PATH (`cargo install --path apps/hal2-cli-records`
from hal2's `code/rust/`). Run it from the repository, or pass `--repo <dir>`. The skill only calls hal2; hal2 calls
no skill.

**Without the binary** (`command -v "$A"` finds nothing; a machine or cloud session without hal2) the skill still
works, read-only and advisory:
- `/adr check` prints the one line `records unchecked: hal2-cli-records is not installed` and passes: hal2's landing
  gate (`records-check`) is where the check is enforced.
- `for`, `search`, `list`, `show` read the files themselves: `grep -l` over `.adr/*.md` for words and for
  `applies_to` globs that match the path, the front matter's `status` and `title` for the list, the file itself for
  `show`; say that the answer comes from a plain read.
- `add`, an amendment's regeneration (`index`, `intent`) and the decision record's form need the binary: write
  nothing, tell the user to install it (the command above) and stop.

| Call | Does |
|---|---|
| `/adr <decision>` | [promote](#promote-a-decision) a decision: the ladder, then a new record or an amendment |
| `/adr for <path>...` | `$A for <path>...`: the accepted records that bind those files; read them before changing the files |
| `/adr search <words>` | `$A search <words>`: records holding every word (title hits first); then `$A show <slug>` for the ones that matter |
| `/adr list [status]` | `$A list [--status proposed\|accepted\|deprecated\|superseded]` |
| `/adr show <slug>` | `$A show <slug>` |
| `/adr check` | `$A check`: the one check of every record the repository holds (its `.hal/records.toml` says which kinds apply; the binary knows the rest), each problem ending in its rule; fix every line it prints. Exit 2: a usage or read error, 3: the binary is older than the repository's `checker` asks (install a newer one). Without the binary: the advisory line above |
| `/adr help`, `/adr h` | print this table and stop |

## Promote a decision

1. **The ladder** (record-formats, rule 4). A question is an entry of the plan's `questions.md`; its answer, and
   every other choice of the plan, an entry of its `decisions.md` (the plan skill's ledger). A decision becomes a
   record only when **a session that never reads this plan would have to know it to do its own work right**: it
   binds work outside the plan's steps, or after the plan has landed. Never promoted: the plan's order and who does
   what, a go or a stop, a base, a number or a name reserved for the plan's branches. Not promoted: say so in one
   line and leave it in the ledger.
   A new term (a word the project uses in one meaning) is no record: it is an entry of the root `GLOSSARY.md`
   (`**Term**:` and one or two sentences, an optional `_Avoid_:` line; `hal2-cli-records check` holds its shape);
   a term the user means the same way in every repository goes into `~/.claude/GLOSSARY.md`.
2. **Is it already decided?** `$A search <its key words>` and `$A for <the files it binds>`. A record that says the
   same: link it from the ledger entry, write nothing. A record whose rule it changes in part: an **amendment**
   (step 4). A record it replaces as a whole: a **new record** that supersedes it (step 3).
3. **A new record.** Pick the slug from the rule, not from the plan (`small-files`, never `plan-0206-decision-3`);
   no number is allocated.
   ```bash
   $A add <slug> --title "<the rule in a few words>" --description "<one sentence, at most 200 characters>" \
      [--status accepted] --origin plans/<NNNN>-<slug>/plan.md [--origin research/<NNNN>-<slug>/research.md] \
      [--applies-to "<glob>"]...
   ```
   It writes the skeleton and the index. Fill it in: **Context** (what forced the decision, links instead of
   copies), **Decision** (numbered rules: other records and code comments cite "rule 4", so numbers never change),
   **Consequences**, **Confirmation** (how a violation is found: the check, test or lint, and then its path in
   `enforced_by`, a file that names the record's slug; prose only when nothing checks it, and say so). The user's
   words that decided it are quoted in Context. `status` is `proposed` until the user (or the plan's
   Pre-authorized) accepted it; `--status accepted` when they already did. `applies_to` globs must match tracked
   files (`["**"]` binds everything). A record it replaces: put the old slug into the new one's `supersedes`, the
   new slug into the old one's `superseded_by`, and set the old one's `status: superseded` and `date`.
4. **An amendment.** Append `## Amendment <YYYY-MM-DD>: <title>` to the record it changes: what changes, which
   numbered rule, the user's words; the rule's old text stays where it is. Add the date to the front matter's
   `amended` list, set `date` to it, and add the plan to `origin`. A record whose numbered rules another record
   replaces in part names it in that record's `amends`.
5. **Link both ways.** The plan's ledger entry becomes `promoted` and gets `**Record:** [<slug>](../../.adr/<slug>.md)`;
   the record's `origin` names `plans/<NNNN>-<slug>/plan.md`. Only the entry's state and that line change; its
   text is never reworded.
6. **Regenerate and check**, then fix every line they print:
   ```bash
   $A index && $A intent     # .adr/index.md and INTENT.md's decision log: generated, never edited by hand
   $A generated --check      # AGENTS.md's generated Rules and the other generated blocks (--write writes them)
   $A check                  # every record, the plan folders' ledgers included (the link's both sides)
   ```
   A rule every agent must know before it reads any file also gets a `rule:` key in the record's front matter (one
   line, `MUST`, `MUST NOT`, `NEVER` or `SHOULD` in capitals, at most 200 characters, no link; `$A add ... --rule
   "<rule>"` writes it): where `AGENTS.md`'s Rules are generated (its `<!-- generated: rules -->` block), run
   `$A generated --write` and never edit the bullet by hand; elsewhere write the line and the record's link into
   `AGENTS.md`'s Rules. A path-scoped rule gets none: `$A for <path>` finds it.
7. Commit the record, the index, `INTENT.md`, `AGENTS.md` and the ledger together (`docs(adr): <slug>: <what>`), or leave them
   to the step's commit when a plan is running. Never push or land for it.

## Rules

- **One home per fact.** The record holds context, decision, consequences and confirmation; the ledger entry, the
  index and INTENT.md's log only link it or show its `description`. Never copy a rule into a plan, a handoff or
  `AGENTS.md` beyond its one line.
- **The index and the log are generated.** A row written by hand between INTENT.md's markers fails the landing;
  `.adr/index.md` is overwritten.
- **A record is amended, never rewritten**: a rule that is replaced as a whole gets a new record and
  `superseded_by` on the old one; history stays readable.
- **A front matter that is valid but untrue is the failure to prevent**: after any change of a record run step 6.
- A repository without `.adr/` in this format has no records: decisions that outlive a plan go to its intent doc
  (the handoff skill's step 1), and this skill says so instead of creating a first record unasked.
