# skills

The agent skills plugin `divramod-skills` (Claude Code, Codex and other Agent Skills harnesses): planning, handoff, landing, the farmer, the tollman and summaries.

Imported from the skills repository by plan 0233 (its `import.sh`); published to
[divramod/agent-plugins](https://github.com/divramod/agent-plugins) as
`plugins/divramod-skills` by the publish job ([claude-code-plugins](../../../../.adr/claude-code-plugins.md)). Install it
(more in that repository's README):

```
/plugin install divramod-skills --marketplace divramod/agent-plugins
```

## Module map

- [.claude-plugin/plugin.json](.claude-plugin/plugin.json): the Claude Code manifest, every skill listed; its
  `version` is the plugin's ([.codex-plugin/plugin.json](.codex-plugin/plugin.json) keeps the same name and version).
- [aliases.json](aliases.json): the shortcut skills `h` (`/handoff`), `c` (`/handoff continue`), `hv` (`/halverse`), `daily` (`/daybook`), `uat` (`/user-acceptance-tests`), `gp` (`/git-push`) and `d` (`/design`), generated into
  `skills/shortcuts/<name>/` by `scripts/gen-aliases.py`.
- [docs/selfimprovement/common/](docs/selfimprovement/common/): notes on agent mistakes the skills guard against.
- [LICENSE](LICENSE): MIT.
- `scripts/`: the plugin's own checks and installers, each with its `test_*.py`.
  - [check-plugins.py](scripts/check-plugins.py): the manifests agree with `skills/`, each skill's front matter, the
    prerequisite scripts, the shortcut skills up to date.
  - [check-agent-starts.py](scripts/check-agent-starts.py): no skill script starts an agent session or types `/exit`.
  - [gen-aliases.py](scripts/gen-aliases.py): writes the shortcut skills from `aliases.json`.
  - [install-skills.py](scripts/install-skills.py), [link-skills.sh](scripts/link-skills.sh) (a wrapper that runs
    install-skills.py): link every skill, flat or in a category folder, into `~/.claude/skills` and `~/.agents/skills`
    (a local install instead of the plugin); a clash only warns (exit 0), two skills of one name in different
    categories exit 1 and link nothing, `--check` exits 1 naming each unlinked skill, `--unlink` removes the links,
    `--quiet` prints only changes; links gone dangling at a move are relinked.
  - [changed_tests.py](scripts/changed_tests.py): the tests of the skills (and plugin scripts) the paths on its
    stdin touch, the skills unit's check of a smuggle (hal2's `.hal/smuggle.toml`).
  - [skillpath.py](scripts/skillpath.py), [skillpath.sh](scripts/skillpath.sh): how a script finds a sibling skill,
    flat or in a category (`sibling(name)`, `skill_dir name`).
- `skills/<name>/`: one skill each, its `SKILL.md` (what the agent reads), its `scripts/` (with tests), templates and
  references.
  - `skills/halverse/scripts/`: [halverse.py](skills/actions/halverse/scripts/halverse.py) is the command line (its parser:
    `halverse_args.py`). [cli.py](skills/actions/halverse/scripts/cli.py) makes every call of `hal2-cli-halverse --json` (a
    term's document on its stdin, the CLI's error object for the caller); on it `sources.py` (the terms and the
    ontology as data), `ontology.py`, `check.py` (`/hv check`), `prompt.py` (the correction prompt) and
    [term.py](skills/actions/halverse/scripts/term.py) (`/hv add|change|retire|short`: the fit, the dry run with its proposal
    number, the one writing call that needs that number, the short forms) with `term_report.py` (the lines per file,
    the report, VoiceInk's state) and `term_errors.py` (an advice per error code). `voiceink.py` calls
    `hal2-cli-voiceink` (sync, status, restore, export); `learn.py` and `transcripts.py` count the user's own prompts
    by `pairs.json`. [names.py](skills/actions/halverse/scripts/names.py) (`/hv christen|rechristen|swap|move|avatar|who`) calls
    `hal2-cli-halverse names ...`: the ideas listed for a christening, a refusal worded with its holder, the way to
    reach a named one's field. The tests run on `fake_cli.py`, a fake CLI printing `fixtures/cli/` (`contract/`,
    `sources/`, `term/`, `term-refused/`, the answers recorded by its `make.sh` from the built CLIs; `documents/` the
    terms; `names/` invented answers written by hand after the CLI's documented shapes).

| Skill | What it does |
|---|---|
| [adapt-merge-queue](skills/actions/adapt-merge-queue/SKILL.md) | reorders hal2's merge queue and reserves places |
| [adr](skills/actions/adr/SKILL.md) | writes and finds decision records in hal2's record format |
| [c](skills/shortcuts/c/SKILL.md), [h](skills/shortcuts/h/SKILL.md) | shortcuts: `/handoff continue`, `/handoff` |
| [ci-analyzer](skills/actions/ci-analyzer/SKILL.md) | finds CI waste and bottlenecks in the last runs and ranks them |
| [cleanup](skills/actions/cleanup/SKILL.md) | deletes a worktree's build artifacts |
| [continue](skills/actions/continue/SKILL.md), [pause](skills/actions/pause/SKILL.md) | pause a session's work and pick it up again |
| [continue-all-agent-work](skills/actions/continue-all-agent-work/SKILL.md), [stop-all-agent-work](skills/actions/stop-all-agent-work/SKILL.md) | stop every session for a quiet machine, and undo it |
| [important-interrupt](skills/actions/important-interrupt/SKILL.md) | quiet the whole Mac in one script call (`done` undoes it), no question |
| [create-hal-project](skills/actions/create-hal-project/SKILL.md) | sets up a new hal project: private GitHub repo, `~/a/<name>` with the hal layout, gate, pre-push hook and `.hal/` tasks in the first commit, smug windows; dry run first, acts on the user's go (`scripts/create_project.py`) |
| [create-shot](skills/actions/create-shot/SKILL.md), [shoot](skills/actions/shoot/SKILL.md) | write a shot, list and send open shots |
| [create-worktree-session](skills/actions/create-worktree-session/SKILL.md), [delete-field](skills/actions/delete-field/SKILL.md) | start or stop an agent session in a worktree |
| [daybook](skills/actions/daybook/SKILL.md), [daily](skills/shortcuts/daily/SKILL.md) | the farm's daily chores, open ones carried on, with its plans and watches (`scripts/daybook.py`; format in its [README](skills/actions/daybook/README.md)); `/daily` is the alias |
| [design](skills/actions/design/SKILL.md), [d](skills/shortcuts/d/SKILL.md) | designs a spec's or plan's feats on one generated page `plans/<plan>/design.html` (GUI prototypes in the current look, current vs new flow and ERD, scenarios, states, sequence), versioned and reviewed (accept toggle, comments); `scripts/design.py` (`new`, `render`, `list`, `serve`, `status`, `accepted`); `/d` is the alias |
| [digest-todolist](skills/actions/digest-todolist/SKILL.md) | turns a photo of a to-do list into shots |
| [farmer](skills/roles/farmer/SKILL.md) | the repository's helper session: CI, unsticking sessions, servants for fixes; `scripts/role_duties.py <role> [--repo <dir>]` prints any role skill's effective duties (its `## Duties`, overridden and extended by the repository's `roles/<role>/ROLE.md`); `silence` / `unsilence` (`scripts/silence.py`, also the tollman's): one table line per round with a joined column; `scripts/board.py` (`post`, `list`, `sync`, `--role farmer|tollman`): the message board `roles/farmer/board.jsonl` of its instructions, acks and notes, synced by every tick, and the tollman's, declared in `manifest.toml` |
| [foreman](skills/roles/foreman/SKILL.md), [servant](skills/roles/servant/SKILL.md) | the role skills of a plan's foreman (steps as hands, servants, hitch, handoff, servant fields removed at once) and of its servants (one step, report, never land); `/foreman`, `/servant` print the effective duties |
| [fix-autoclear](skills/actions/fix-autoclear/SKILL.md) | analyses and fixes an autoclear failure |
| [fix-loc](skills/actions/fix-loc/SKILL.md) | the loop that brings files under 300 code lines |
| [fix-tart](skills/actions/fix-tart/SKILL.md) | analyses and fixes a Mac VM (Tart) runner incident: evidence, known cases, doctor (`scripts/evidence.py`, `sources.py`, `signatures.py`) |
| [grill-plan](skills/actions/grill-plan/SKILL.md) | questions a plan until every branch is decided |
| [grill-message](skills/actions/grill-message/SKILL.md) | grills a message draft before it is sent (sense, tone, oversharing, over-optimism, the channel), reads the earlier messages through the CLI map's tools, puts the improved draft into the clipboard; never sends |
| [halverse](skills/actions/halverse/SKILL.md) | `/hv`: shows the ontology (`ontology`), checks the halverse files (`check`), adds, changes and retires a term in four languages (`add`, `change`, `retire`), sets short forms (`short`), counts old words against farm words (`learn`), syncs VoiceInk, prints its correction prompt and writes its import file (`voiceink [status\|restore\|prompt\|export]`), christens the role of a field and keeps its names (`christen`, `rechristen`, `swap`, `move`, `avatar`), finds a named one by a current or earlier name (`who`) |
| [handoff](skills/actions/handoff/SKILL.md) | writes the handoff before a clear and continues from it |
| [list-free-worktrees](skills/actions/list-free-worktrees/SKILL.md) | lists the idle worktree sessions |
| [llm-wiki](skills/actions/llm-wiki/SKILL.md) | a farm's LLM wiki (`office/`): the judgment steps over `hal2-cli-llm-wiki`: ingest a source into atoms, compile pages, query, lint; `references/` holds branch design, the LLM lint and calibration |
| [lookout](skills/actions/lookout/SKILL.md) | global watches: a 5-minute timer runs each due check command as code (0 tokens when quiet), a new find is judged once under a budget, recorded, jotted into the daybook and notified; scripts: `lookout.py`, `runner.py`, `judge.py`, `find.py`, `notify.py`, `checks/email.py` |
| [optimize-skill](skills/actions/optimize-skill/SKILL.md) | improves one skill by its evals under a token cap, after microsoft/skillopt: rule-judged rollouts on `claude -p`, bounded edits, kept only if strictly better on validation, result a `best.diff` the user applies; scripts: `optimize.py`, `loop.py`, `rollout.py`, `judge.py`, `gate.py`, `budget.py` |
| [lord](skills/roles/lord/SKILL.md), [pope](skills/roles/pope/SKILL.md) | the city's head (Burgherr) in the castle `~/a/city` and the planet's highest head (Papst) in the cathedral `~/a/planet` (each place one setting, `HAL_CITY`, `HAL_PLANET`); one duty `state`: `/s` there opens the goals page (3-5 years, life) |
| [mayor](skills/roles/mayor/SKILL.md) | the village's head in `~/a/village`: stops every farm's work and sends everyone back to work; duty `state` opens the 1-year goals page |
| [merge-from-main](skills/actions/merge-from-main/SKILL.md) (`/mfm`), [merge-to-main](skills/actions/merge-to-main/SKILL.md) (`/mtm`), [smuggle](skills/actions/smuggle/SKILL.md) | merge from main, land on main, land from this machine without CI (`/smuggle`; `scripts/smuggle.sh`, `units.py` reads `.hal/smuggle.toml`) |
| [optimize-ci-job](skills/actions/optimize-ci-job/SKILL.md) | takes one CI job deep to cut its runtime and CPU load: the unit `ci-job` measures (`report`, `scan`, `spawns`, `ab`), the skill judges against [causes.md](skills/actions/optimize-ci-job/causes.md); read-only, proposes shots or one farmer brief |
| [plan](skills/actions/plan/SKILL.md), [research](skills/actions/research/SKILL.md) | plans and research docs |
| [prune](skills/actions/prune/SKILL.md) | cleans a farm's fields deterministically as a run: free fields removed, build folders trimmed while the disk is short (`scripts/prune.py`) |
| [restart-claude-code-sessions](skills/actions/restart-claude-code-sessions/SKILL.md) | restarts every running Claude session in place (same pane, same conversation) through `hal2-cli-agents restart --all`, e.g. after a login to another account |
| [spec](skills/actions/spec/SKILL.md) | writes a feature's spec before its plan: a plan folder with `spec.md` and the design page, no `plan.md`, numbered with the plans (`scripts/spec.py`: `new`, `show`, `list`, `approve`); `/plan new --spec <n>` plans it later |
| [get-open-questions](skills/actions/get-open-questions/SKILL.md) (alias q) | lists the session's open, answered or all questions in the Q form (`scripts/q.py`) |
| [get-state](skills/actions/get-state/SKILL.md) (alias s) | opens the session's role page in the browser (`--text` the table of every worktree, the own row marked): `scripts/state.py`, `role.py`, `page.py` (`grid.py`, `table.js`, `table.css`), `serve.py`, `serve_launch.py`, `views.py`, `view_<role>.py` (farmer, foreman, goals, steward, tollman) with `ledger_sources.py`, `steward_sources.py`, `tollman_sources.py`, `state_sources.py`, `state_table.py`, `farmer_link.py` |
| [sanity-watch](skills/actions/sanity-watch/SKILL.md) | resumes sessions that stopped abnormally |
| [steward](skills/roles/steward/SKILL.md) | the role skill of the session in the main checkout: answer, shots, small work, hand-over to the farmer, daybook |
| [tell](skills/actions/tell/SKILL.md) | summarizes a URL, file or topic into a note |
| [transplant](skills/actions/transplant/SKILL.md) | moves a foreman with its branch, plan and handoff to another field; only the user starts it (`.adr/transplant-by-command.md`) |
| [tollman](skills/roles/tollman/SKILL.md) | the third base role: brings the foremen's ready wagons through the merge queue into the barn as wagon trains, with its own field, timer, message board (the farmer frame's `board.py`) and yard job; the farmer's frame (`farmer/scripts`) runs its rounds; its scripts: `tollman.py`, `trains.py`, `chain.py`, `trial.py`, `proof.py`, `stack_red.py` (a red stack-test after the merge), `pretest.py`, `pretest_jobs.py`, `pretest_markers.py` and `pretest_train.py` (the local pretest before a train's push), `engine.py`, `carrier.py` (the carrier's remote branch put back on a base), `train_state.py`, `yard.py`, `yard_rules.py`, `yard_report.py`, `boss.py`, `flaky_brief.py` (a load-flaky test's brief in the farmer's delegation ledger) |
| [git-push](skills/actions/git-push/SKILL.md) (alias gp) | commits the uncommitted files as Conventional Commits and pushes: `scripts/gp.py` (`scan`, `commit`, `ignore`, `push`) groups them by unit, never commits a secret, asks about ignore-candidates, adds the `Worktree:`/`Plan:`/`Step:` trailers and refuses a default branch that lands through the merge queue |
| [user-acceptance-tests](skills/actions/user-acceptance-tests/SKILL.md) (alias uat) | walks a plan's UATs with the user, one check per message, and records each verdict through `hal2-cli-plans uat` (`scripts/uat.py`: `list`, `open`, `show`, `next`, `set`; no second tracker) |
| [workqueue-check](skills/actions/workqueue-check/SKILL.md) | compares the work queue's numbers of a window with the window before and the benchmarks with their baseline, ranks what got slower and proposes the fix (`scripts/check.py`, `gather.py`, `findings.py`) |

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
- **Tests**: fast on CI, never by dropping one ([fast-tests](../../../../.adr/fast-tests.md)); how, with this plugin's
  helpers (`testkit.py`, `handoff_testkit.py`, `test_helper.bash`): [docs/fast-tests.md](../../../../docs/fast-tests.md).

## Develop

From this folder:

```
python3 scripts/check-plugins.py
python3 -m unittest discover -s scripts
for d in skills/*/*/scripts; do (cd "$d" && python3 -m unittest discover -s . -p 'test_*.py'); done
bats skills/actions/merge-to-main/scripts skills/actions/smuggle/scripts
claude plugin validate --strict .
```

The plugin's version is bumped by the landing, never by hand
([claude-code-plugins](../../../../.adr/claude-code-plugins.md)).
