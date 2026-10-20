---
name: create-hal-project
description: Set up a new hal project in one call — a private GitHub repo divramod/<name>, checked out in ~/a/<name> with the hal layout in its first commit (README with the one-page hal brief, CLAUDE.md, AGENTS.md, INTENT.md, GLOSSARY.md, .gitignore, roles/farmer/ROLE.md, the hal folders, a language-agnostic gate and pre-push hook, .hal/setup.toml, LICENSE placeholder), and a window named by the alias in each of the user's smug ymls (~/.config/smug). Always a dry run first that shows every action as create or exists; it acts only on the user's go in this session (a GitHub repo is outward-facing), is idempotent and never overwrites an existing repo, folder or smug window. Prints the next steps (fields, farmer; no tollman or CI yet). Use when the user says /create-hal-project, "new hal project", "set up a new project", "bootstrap a repo" or "create a project with alias". `/create-hal-project h` shows help.
---

# create-hal-project

`create_project.py` does every deterministic step (gh, git, templates, smug text); the model only judges and reports.
`S=<skill-dir>/scripts`.

| Call | Does |
|---|---|
| `/create-hal-project <name> <alias>` | dry run, show the plan, ask for the go, then apply |
| `... --dry-run` | only the plan, changes nothing |
| `... --smug a.yml,b.yml` | only these ymls of `~/.config/smug` (default: all) |
| `... --owner <owner>` | another GitHub owner (default `divramod`) |
| `... --json` | machine-readable `actions` and `next` |
| `/create-hal-project h` | print this table and stop |

## Run

1. Always first: `python3 $S/create_project.py --dry-run [--json] <name> <alias>`. Exit 0 prints one line per action
   (`repo`, `checkout`, `file`, `commit`, `push`, `hook`, `smug`), each `create`, `exists` or `skip`. Exit 1: a command failed
   or the name is bad; exit 2: `gh` or `git` is missing (say so, stop); exit 3: `~/a/<name>` is a foreign non-empty
   folder (report it, stop).
2. Show the plan in a few lines. An `exists` (repo, checkout, smug window) is kept as it is: say which, and judge only
   whether that is what the user meant (a half-made project is finished by the `create` actions; a different repo of
   that name is not touched).
3. Ask the user for the go in plain text and wait. The repo is private and outward-facing: no go, no run. A go given
   earlier for another project, or a plan's pre-authorisation, is not one.
4. On the go: the same call without `--dry-run`. Report the actions done and the printed next steps.

## The first commit

The flat files (README, CLAUDE.md, AGENTS.md, INTENT.md, GLOSSARY.md, `.gitignore`, the farmer's ROLE.md) and
`scripts/foundation.py`'s tree (plan 0408): the hal folders with `.gitkeep`, the gate `code/bash/scripts/gate/main.sh`
(`list`, `<job>`, `all`; jobs found by what exists, green on the empty layout), the pre-push unit, `.hal/setup.toml`,
`.hal/cleanup`, `.gitattributes`, a LICENSE placeholder. The `hook` action links the pre-push hook into the checkout's
`.git` after the push (`exists` when linked, `skip` for another tool's hook: reported, never overwritten).

## Next steps (printed, not run)

Create fields 00-09 (`hal2-cli-git worktree ...`); start the farmer only in `farmer-<repo>`
(`hal2-cli-git worktree run farmer-<repo> --agent claude`, then the user's `/farmer start`); the new repo has no
tollman and no merge-to-main workflow yet; secrets via `hal2-cli-secrets set` from a field; run `code/bash/scripts/gate/main.sh all`; choose the LICENSE before going public. Smug ymls are edited only,
never committed (`~/.config/smug` is the user's dotfiles).

## Report

Short: the repo URL, the checkout, the smug files changed, and the next steps. Never print secrets or the environment.
