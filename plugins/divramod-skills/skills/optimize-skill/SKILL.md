---
name: optimize-skill
description: Improve one skill by evals under a hard token cap, after microsoft/skillopt (MIT) — a rollout runs the skill's SKILL.md on each eval task in a lean headless `claude -p`, a rule judge scores it by the eval's `checks` (code, no model), the optimizer reflects on the failed train rollouts and proposes bounded edits, and a candidate is kept only if it strictly beats the incumbent on the validation split. It never writes the skill: the result is a `best.diff` the user applies. Runs on the subscription (`ANTHROPIC_API_KEY` is removed from the child env). Use when the user says /optimize-skill, "optimize this skill", "improve the skill by evals", "skillopt" or "make this skill score better". `/optimize-skill h` shows help.
---

# optimize-skill

**Goal: a skill that scores better on its own evals, proven on held-out tasks, at a token cost fixed before the run.**
Design: [research 0100](../../../../../../../research/0100-skill-optimizer/research.md), [plan 0390](../../../../../../../plans/0390-optimize-skill/plan.md).
Idea and loop from microsoft/skillopt (MIT). `S=<skill-dir>/scripts`.

| Call | Does |
|---|---|
| `/optimize-skill <skill>` | the whole flow below; `<skill>` is a name (the plugin's `skills/*/<name>`) or a folder |
| `/optimize-skill estimate <skill>` | `python3 $S/optimize.py estimate <dir>`: the token estimate, no model call |
| `/optimize-skill status [<skill>]` | `python3 $S/optimize.py status`: scores baseline -> best, tokens, stop reason |
| `/optimize-skill diff <skill>` | `python3 $S/optimize.py diff <skill>`: the last run's `best.diff` |
| `/optimize-skill h`, `help` | print this table and stop |

## Flow

1. **Resolve** the folder of the skill (it holds `SKILL.md`); none found: say so and stop.
2. **Init**: `python3 $S/optimize.py init <dir>`. It reuses `evals/evals.json` and counts its splits. On a skeleton
   (`is_skeleton`) you draft the evals, the only judgment here: 6-10 `train` and 4-5 `val` tasks, each a realistic user
   prompt with rule `checks` (code-checkable: file exists, text contains, command ran), never a model-judged check.
   Show them and write them only after the user agrees; then `init` again.
3. **Estimate**: `python3 $S/optimize.py estimate <dir>`; tell the user the tokens against the cap (defaults:
   3 epochs, 2 candidates, `--max-tokens 5000000`, `--max-rollouts 80`) and ask before a run above the cap.
4. **Run**: `python3 $S/optimize.py run <dir> [--max-tokens N ...]`. The loop stops on a perfect train or val score (a
   perfect val cannot be beaten), two epochs without a winner, the epochs, or the cap (a stop on the cap is still a result).
   A skill whose scripts need more than their own folder gets it by `--support DEST[=SRC]` (no SRC: an empty
   folder), e.g. get-open-questions: `--support .git --support .claude/.claude-plugin --support
   .claude/scripts=<plugin>/scripts` and its siblings in the category layout (`.claude/skills/actions/handoff`,
   `.claude/skills/roles/farmer/SKILL.md`, invisible to the rollout as skills).
5. **Report**: `status`, then `diff`. Say baseline -> best on train and val, the tokens and the stop reason. Apply
   the diff (`apply` in `status --json`: `git -C <root> apply <best.diff>`) **only on the user's word**; an empty diff
   means nothing beat the baseline.

## Code and model

Code: the eval set check, rollouts, the rule judge, the gate (strictly better on val, ties rejected), the budget
ledger, applying edits and the diff. Model: the rollouts (`--model`, default haiku), the reflection and the edit
proposals (`--optimizer-model`, default sonnet), and you drafting evals. Every call is a one-shot `claude -p` without
session persistence on the subscription; the run reads and writes only its run folder
(`$OPTIMIZE_SKILL_HOME`, default `~/.cache/hal2/optimize-skill`) and a temporary workspace, never the skill's folder.
Validation tasks never reach the optimizer.
A rollout's Bash runs only in Claude Code's sandbox (writes only its workspace, no network; none on native
Windows), so an eval whose skill needs more fails there.

Exit codes of `optimize.py`: 0 done (a cap stop too), 1 a refused input or no run, 2 a usage error; print the line it
gave on 1.
