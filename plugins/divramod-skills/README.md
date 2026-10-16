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
- [aliases.json](aliases.json): the shortcut skills `h` (`/handoff`), `c` (`/handoff continue`), `hv` (`/halverse`) and `daily` (`/daybook`), generated into
  `skills/h`, `skills/c`, `skills/hv` and `skills/daily` by `scripts/gen-aliases.py`.
- [docs/selfimprovement/common/](docs/selfimprovement/common/): notes on agent mistakes the skills guard against.
- [LICENSE](LICENSE): MIT.
- `scripts/`: the plugin's own checks and installers, each with its `test_*.py`.
  - [check-plugins.py](scripts/check-plugins.py): the manifests agree with `skills/`, each skill's front matter, the
    prerequisite scripts, the shortcut skills up to date.
  - [check-agent-starts.py](scripts/check-agent-starts.py): no skill script starts an agent session or types `/exit`.
  - [gen-aliases.py](scripts/gen-aliases.py): writes the shortcut skills from `aliases.json`.
  - [install-skills.py](scripts/install-skills.py), [link-skills.sh](scripts/link-skills.sh): link every skill into
    `~/.claude/skills` and `~/.agents/skills` (a local install instead of the plugin); install-skills.py: a clash only
    warns (exit 0), `--check` exits 1 naming each unlinked skill, `--quiet` prints only changes.
- `skills/<name>/`: one skill each, its `SKILL.md` (what the agent reads), its `scripts/` (with tests), templates and
  references.
  - `skills/halverse/scripts/`: [halverse.py](skills/halverse/scripts/halverse.py) is the command line (its parser:
    `halverse_args.py`). [cli.py](skills/halverse/scripts/cli.py) makes every call of `hal2-cli-halverse --json` (a
    term's document on its stdin, the CLI's error object for the caller); on it `sources.py` (the terms and the
    ontology as data), `ontology.py`, `check.py` (`/hv check`), `prompt.py` (the correction prompt) and
    [term.py](skills/halverse/scripts/term.py) (`/hv add|change|retire|short`: the fit, the dry run with its proposal
    number, the one writing call that needs that number, the short forms) with `term_report.py` (the lines per file,
    the report, VoiceInk's state) and `term_errors.py` (an advice per error code). `voiceink.py` calls
    `hal2-cli-voiceink` (sync, status, restore, export); `learn.py` and `transcripts.py` count the user's own prompts
    by `pairs.json`. The tests run on `fake_cli.py`, a fake CLI printing `fixtures/cli/` (`contract/`, `sources/`,
    `term/`, `term-refused/`, the answers recorded by its `make.sh` from the built CLIs; `documents/` the terms).

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
| [daybook](skills/daybook/SKILL.md), [daily](skills/daily/SKILL.md) | the farm's daily chores, open ones carried on, with its plans and watches (`scripts/daybook.py`; format in its [README](skills/daybook/README.md)); `/daily` is the alias |
| [digest-todolist-picture](skills/digest-todolist-picture/SKILL.md) | turns a photo of a to-do list into shots |
| [farmer](skills/farmer/SKILL.md) | the repository's helper session: CI, unsticking sessions, servants for fixes; `silence` / `unsilence` (`scripts/silence.py`, also the wagon master's): one table line per round with a joined column |
| [fix-autoclear](skills/fix-autoclear/SKILL.md) | analyses and fixes an autoclear failure |
| [fix-loc](skills/fix-loc/SKILL.md) | the loop that brings files under 300 code lines |
| [grill](skills/grill/SKILL.md) | questions a plan until every branch is decided |
| [halverse](skills/halverse/SKILL.md) | `/hv`: shows the ontology (`ontology`), checks the halverse files (`check`), adds, changes and retires a term in four languages (`add`, `change`, `retire`), sets short forms (`short`), counts old words against farm words (`learn`), syncs VoiceInk, prints its correction prompt and writes its import file (`voiceink [status\|restore\|prompt\|export]`) |
| [handoff](skills/handoff/SKILL.md) | writes the handoff before a clear and continues from it |
| [list-free-worktrees](skills/list-free-worktrees/SKILL.md) | lists the idle worktree sessions |
| [mfm](skills/mfm/SKILL.md), [mtm](skills/mtm/SKILL.md), [mtm-fastlane](skills/mtm-fastlane/SKILL.md) | merge from main, land on main, land without CI |
| [plan](skills/plan/SKILL.md), [research](skills/research/SKILL.md) | plans and research docs |
| [q](skills/q/SKILL.md) | lists the session's open, answered or all questions in the Q form (`scripts/q.py`) |
| [s](skills/s/SKILL.md) | prints the state of every worktree as one table, the session's own row marked (`scripts/state.py`, `state_sources.py`, `state_table.py`, `farmer_link.py`) |
| [sanity-watch](skills/sanity-watch/SKILL.md) | resumes sessions that stopped abnormally |
| [tell](skills/tell/SKILL.md) | summarizes a URL, file or topic into a note |
| [transplant](skills/transplant/SKILL.md) | moves a foreman with its branch, plan and handoff to another field; only the user starts it (`.adr/transplant-by-command.md`) |
| [wagon-master](skills/wagon-master/SKILL.md) | the third base role: brings the foremen's ready wagons through the merge queue into the barn as wagon trains, with its own field, timer, message board and yard job; the farmer's frame (`farmer/scripts`) runs its rounds; its scripts: `wagon_master.py`, `trains.py`, `chain.py`, `trial.py`, `proof.py`, `stack_red.py` (a red stack-test after the merge), `pretest.py`, `pretest_jobs.py`, `pretest_markers.py` and `pretest_train.py` (the local pretest before a train's push), `engine.py`, `carrier.py` (the carrier's remote branch put back on a base), `train_state.py`, `board.py` (`list`, `sync`), `yard.py`, `yard_rules.py`, `yard_report.py`, `boss.py` |

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
