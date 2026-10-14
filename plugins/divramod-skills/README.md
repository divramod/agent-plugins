# skills

The agent skills plugin `divramod-skills` (Claude Code, Codex and other Agent Skills harnesses): planning, handoff, landing, the farmer, the wagon master and summaries.

Imported from the skills repository by plan 0233 (its `import.sh`); published to
[divramod/divramod-claude-code-plugins](https://github.com/divramod/divramod-claude-code-plugins) as
`plugins/divramod-skills` by the publish job ([claude-code-plugins](../../../../.adr/claude-code-plugins.md)). Install it
(more in that repository's README):

```
/plugin install divramod-skills --marketplace divramod/divramod-claude-code-plugins
```

## Module map

- [.claude-plugin/plugin.json](.claude-plugin/plugin.json): the Claude Code manifest, every skill listed; its
  `version` is the plugin's ([.codex-plugin/plugin.json](.codex-plugin/plugin.json) keeps the same name and version).
- [aliases.json](aliases.json): the shortcut skills `h` (`/handoff`), `c` (`/handoff continue`) and `hv` (`/halverse`), generated into
  `skills/h`, `skills/c` and `skills/hv` by `scripts/gen-aliases.py`.
- [docs/selfimprovement/common/](docs/selfimprovement/common/): notes on agent mistakes the skills guard against.
- [LICENSE](LICENSE): MIT.
- `scripts/`: the plugin's own checks and installers, each with its `test_*.py`.
  - [check-plugins.py](scripts/check-plugins.py): the manifests agree with `skills/`, each skill's front matter, the
    prerequisite scripts, the shortcut skills up to date.
  - [check-agent-starts.py](scripts/check-agent-starts.py): no skill script starts an agent session or types `/exit`.
  - [gen-aliases.py](scripts/gen-aliases.py): writes the shortcut skills from `aliases.json`.
  - [install-skills.py](scripts/install-skills.py), [link-skills.sh](scripts/link-skills.sh): link every skill into
    `~/.claude/skills` and `~/.agents/skills` (a local install instead of the plugin).
- `skills/<name>/`: one skill each, its `SKILL.md` (what the agent reads), its `scripts/` (with tests), templates and
  references.

| Skill | What it does |
|---|---|
| [adapt-merge-queue](skills/adapt-merge-queue/SKILL.md) | reorders hal2's merge queue and reserves places |
| [adr](skills/adr/SKILL.md) | writes and finds decision records in hal2's record format |
| [c](skills/c/SKILL.md), [h](skills/h/SKILL.md) | shortcuts: `/handoff continue`, `/handoff` |
| [ci-analyzer](skills/ci-analyzer/SKILL.md) | finds CI waste and bottlenecks in the last runs and ranks them |
| [cleanup](skills/cleanup/SKILL.md) | deletes a worktree's build artifacts |
| [continue](skills/continue/SKILL.md), [pause](skills/pause/SKILL.md) | pause a session's work and pick it up again |
| [continue-all-agent-work](skills/continue-all-agent-work/SKILL.md), [stop-all-agent-work](skills/stop-all-agent-work/SKILL.md) | stop every session for a quiet machine, and undo it |
| [create-shot](skills/create-shot/SKILL.md), [shoot](skills/shoot/SKILL.md) | write a shot, list and send open shots |
| [create-worktree-session](skills/create-worktree-session/SKILL.md), [delete-worktree-session](skills/delete-worktree-session/SKILL.md) | start or stop an agent session in a worktree |
| [digest-todolist-picture](skills/digest-todolist-picture/SKILL.md) | turns a photo of a to-do list into shots |
| [farmer](skills/farmer/SKILL.md) | the repository's helper session: CI, unsticking sessions, servants for fixes |
| [fix-autoclear](skills/fix-autoclear/SKILL.md) | analyses and fixes an autoclear failure |
| [fix-loc](skills/fix-loc/SKILL.md) | the loop that brings files under 300 code lines |
| [grill](skills/grill/SKILL.md) | questions a plan until every branch is decided |
| [halverse](skills/halverse/SKILL.md) | shows the user's ontology, counts old words against farm words and syncs the words into VoiceInk (`/hv`) |
| [handoff](skills/handoff/SKILL.md) | writes the handoff before a clear and continues from it |
| [list-free-worktrees](skills/list-free-worktrees/SKILL.md) | lists the idle worktree sessions |
| [mfm](skills/mfm/SKILL.md), [mtm](skills/mtm/SKILL.md), [mtm-fastlane](skills/mtm-fastlane/SKILL.md) | merge from main, land on main, land without CI |
| [plan](skills/plan/SKILL.md), [research](skills/research/SKILL.md) | plans and research docs |
| [q](skills/q/SKILL.md) | lists the session's open, answered or all questions in the Q form (`scripts/q.py`) |
| [s](skills/s/SKILL.md) | prints the state of every worktree as one table, the session's own row marked (`scripts/state.py`, `state_sources.py`, `state_table.py`, `farmer_link.py`) |
| [sanity-watch](skills/sanity-watch/SKILL.md) | resumes sessions that stopped abnormally |
| [tell](skills/tell/SKILL.md) | summarizes a URL, file or topic into a note |
| [wagon-master](skills/wagon-master/SKILL.md) | the third base role: brings the foremen's ready wagons through the merge queue into the barn as wagon trains, with its own field, timer, message board and yard job; the farmer's frame (`farmer/scripts`) runs its rounds; its scripts: `wagon_master.py`, `trains.py`, `trial.py`, `engine.py`, `train_state.py`, `board.py` (`list`, `sync`), `yard.py`, `yard_rules.py`, `yard_report.py`, `boss.py` |

## Rules

The skills repository's own rules (its AGENTS.md), kept for this unit:

- **Skill data**: a skill that creates data of its own (summaries, downloads, caches) keeps it under
  `~/skills/<skill-name>/`, never in a shared folder; an environment variable may override the root
  (`<SKILL_NAME>_ROOT`). When the default moves and data is at the old place, the skill stops with the command that
  moves it.
- **Deterministic first**: what can be done deterministically is done by a skill's scripts or a CLI; the model does
  only the judgment ([deterministic-first](../../../../.adr/deterministic-first.md) where hal2 has it).
- **Skill shape**: every `SKILL.md` has front matter `name` (its folder's name) and `description`, one `# ` heading
  and a table of calls with a `/<name> h` row before the first numbered section; `hal2-cli-records check` holds it
  (the Skill kind; `c` and `h` are excluded in hal2's `.hal/records.toml`).
- **Scripts**: deterministic work lives in `skills/<name>/scripts/` or a CLI. A scripts folder whose scripts call
  external tools checks each before use (exit 2 naming the tool) and ships executable `check-prerequisites.sh` and
  `install-prerequisites.sh` (a split skill also aggregators at the top of `scripts/`); `check-plugins.py` enforces it.
- **No agent starts**: no script starts an agent session itself or types `/exit`; sessions start through hal2
  (`hal2-cli-git worktree run`, `hal2-cli-agents spawn`) and stop through `hal2-cli-agents stop`
  (`check-agent-starts.py`).
- **Verify**: build and run what you changed, run its tests, add a test where none covers it, say what you could not
  verify.

## Develop

From this folder:

```
python3 scripts/check-plugins.py
python3 -m unittest discover -s scripts
for d in skills/*/scripts; do (cd "$d" && python3 -m unittest discover -s . -p 'test_*.py'); done
bats skills/mtm/scripts skills/mtm-fastlane/scripts
claude plugin validate --strict .
```

The plugin's version is bumped by the landing, never by hand
([claude-code-plugins](../../../../.adr/claude-code-plugins.md)).
