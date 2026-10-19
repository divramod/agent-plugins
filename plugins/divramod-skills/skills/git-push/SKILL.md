---
name: git-push
description: Commit everything uncommitted as Conventional Commits and push — `gp.py scan` groups the changed files by unit (a code unit, a plan, docs, a top folder) and classes each as commit, secret (never committed) or ignore-candidate (build output, caches, logs, editor files, large binaries); you ask the user about the ignore-candidates in one plain-text question in the Q form, write one descriptive `<type>(<scope>): <subject>` per group (with a current plan the scope is `<NNNN>|<step>`), commit each group with the repository's trailers (`Worktree:`, `Plan:`, `Step:`) and push the branch without force. It refuses to push the default branch of a repository that lands through a merge queue (`/mtm` does that). `/gp` does all of it, `/gp scan` only shows the groups, `/gp push` only pushes, `/gp <hint>` gives the commit's subjects a hint. Use when the user says /gp, "commit and push", "commit everything", "push my work" or "commitizen commits". `/gp h` shows help.
---

# git-push (alias gp)

`S=<skill-dir>/scripts`. Decision D12 of hal2 plan 0364. `gp.py` is the deterministic part (what changed, which unit, which
class, the staging, the trailers, the push); you only word the subjects and ask the one question. Never `git add -A`, never
`git commit` or `git push` by hand here, never a force push.

| Call | Does |
|---|---|
| `/git-push` (`/gp`) | scan, ask about ignore-candidates, commit every group, push, report |
| `/git-push scan` | only `python3 $S/gp.py scan` and print it |
| `/git-push push` | only `python3 $S/gp.py push` |
| `/git-push h` | print this table and stop |

## Steps

1. **Scan**: `python3 $S/gp.py scan --json`. `clean` true: say "nothing to commit" and go to step 5 (a push of earlier
   commits is still fine). `conflicts` not empty: say which files and stop (resolving them is not this skill's job).
2. **Ignore-candidates** (`ignore_candidates`, each with a `pattern`, a `reason` and its files) and **secrets** (`secrets`):
   when either list has entries, ask once, in plain text after listing them (the question dialog would hide the list), in the
   Q form of the global AGENTS.md: numbered `Q<n>`, exactly three options, the recommended first, clear on its own, e.g.
   `Q1: 3 untracked paths look like build output or caches (target/ 214 files, *.log 2 files, .DS_Store 1 file) and 1 file
   is a secret (.env, never committed). What should happen to them?` with `a) (Recommended)` add the patterns to .gitignore
   (`gp.py ignore <pattern>...`; the secret's path too), `b)` leave them untouched and uncommitted, `c)` commit the candidates
   anyway (`--also <path>` on the group's commit; never a secret). Wait for the answer, then act: a) runs `gp.py ignore`
   (the changed `.gitignore` is then a group of its own: commit it as `chore(gitignore): <what is ignored>`) and rescans.
   No candidate and no secret: no question. A secret is always only reported, never committed.
3. **Subjects**: read each group's diff (`git diff -- <files>`; new files by reading them) and write one subject per group:
   `<type>(<scope>): <what changed>`, type one of `feat fix docs test ci perf style refactor build chore`, the group's
   `scope` as the scope: with a plan in `plans/CURRENT_PLAN` the scan gives its number, `<NNNN>`, and a step's work
   adds `|<step>` (`feat(0391|15): ...`, hal2 plan 0391 D22); without a plan the unit (a docs group: `docs(docs): ...`), lower-case, imperative, no period, at most 72
   characters, never `update` or `misc edits`; a `!` before the colon marks a breaking change. A body (`--body`) only
   when the why is not obvious. A `docs/` group is always its own commit; a mixed unit that holds clearly unrelated
   changes may be split by asking for it: files of one unit stay in one commit.
4. **Commit** each group: `python3 $S/gp.py commit --group <unit> --subject "<subject>" [--body "<why>"]
   [--step <n>/<total>] [--trailer "<attribution line>"]...`. The script validates the subject, stages and commits exactly
   that group's files and adds `Worktree:` (in a field), `Plan:` (when `plans/CURRENT_PLAN` names a plan folder) and the
   `--step` you pass; add the session's attribution lines (the `Co-Authored-By:` and `Claude-Session:` lines of the
   system reminder) as `--trailer`s. A refusal on stderr (form, hook) is fixed and the same group committed again, never
   `--no-verify`.
5. **Push**: `python3 $S/gp.py push`. It pushes `HEAD` to the branch of the same name (with `-u` the first time), never forces, and refuses
   the default branch of a repository with a merge-to-main workflow, also as the upstream of the current branch: then say "use /mtm" and stop. A rejected push:
   `git pull --rebase`, then `push` again; if that fails, report and stop.
6. **Report** in few words: a table of hash and subject per commit, the branch pushed, and what was skipped (secrets,
   ignore-candidates left, files left uncommitted).

## Rules

- A secret (`.env*`, `.envrc`, `.npmrc`, `*.tfvars`, `*_SEC`, keys, plain files in `.secrets/`; names match in any case) is never staged, not even on the user's word; say so.
- Ignore-candidates are never committed unasked (step 2); the pattern list comes from the script, not from memory.
- `--repo <dir>` works on another checkout; the group names come from `scan`, never invented.
- Only the files of the scan are touched; this skill never merges, rebases or lands (that is `/mfm` and `/mtm`).

Prerequisites: `scripts/check-prerequisites.sh` (python3, git); without them say so and stop.
