# Branch design

`W=hal2-cli-llm-wiki`, as in [SKILL.md](../SKILL.md). Read when an atom fits no branch of `office/README.md`'s `## Branches` table, or when `lint brief` proposes a merge or
split. A branch is a topic folder `atoms/<branch>/`; pages are named `<branch>-<topic>` and live flat in `pages/`.

## Create a branch yourself, never ask

A new branch is created when **all four** hold (the user's decision, plan 0341 D11):

1. **Independence**: the atoms cannot fit cleanly into an existing branch.
2. **Scale**: 5 or more atoms are expected.
3. **A boundary**: one paragraph says what belongs and what does not.
4. **A talk**: it could anchor 30 minutes of explanation on its own.

Then: add a row `| <branch> | <the one-paragraph boundary> |` to the table in `office/README.md` (the one file written by
hand), write the atoms, and `$W log "branch <name> created: <the criteria that hold, in one line>"`. The user can
merge a branch back; the log line is how it is reviewed.

If a criterion fails: use **tags** on an atom of the nearest branch, or leave the atom deferred (note it in the log).
Branch names are kebab-case, short, and without a trailing topic word that a page name would repeat.

## Merge and split (proposed by `lint brief`)

- Fewer than 3 atoms, or more than 50 % of its atoms also tagged with another branch: **merge** into the closer
  branch (move the atoms by superseding them into the other branch's id, then recompile the pages).
- More than 30 atoms that split naturally into two topics: **split**, each part meeting the four criteria.

Both change ids, so they are proposals: report them (see llm-lint.md), and carry them out only when the user says so
or the lint brief repeats them twice in a row.

## Do not

Do not rename a branch by hand-moving atom files: ids, footers and links break. Do not create a branch for one
source; a source's topic is a tag until it recurs.
