"""The fix orders' message texts (orders.py, hal2 plan 0360 step 6): the order, the barn's own fix, the early and
post-merge words, a second red job (`also`, plan 0522 D16), a fix left local (L106), a refusal, and what the answer's
proof is (`proof_text`, fix_proof.py, plan 0522 D5)."""

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import fix_proof

# L84, L106: the side branch carries the train's generated commit (CHANGELOG.md), which a field's pre-push refuses
PUSH = "`HAL2_PRE_PUSH=0 git push origin {branch}` (the train's own CHANGELOG commit is no change of yours)."
# L113 (fail-fast cancels the rest of a run: a red job's other tests stay unseen), L85 (a gate helper needs its jobs'
# paths): what a fix runs before it is answered; the triage's order says the same (run_triage_text.ORDER)
PROOF = (" Before you answer, run the whole red job, not only its failing test (`code/bash/scripts/gate/main.sh <job> "
         "--branch origin/main`); a fix that touches code/bash/scripts/gate/ also runs `bats "
         "code/bash/scripts/gate/test-select.bats code/bash/scripts/gate/test.bats`.")
HEAD = "tollman (wagon train): fix order {id} for field {field}: train {train} is red ({red}). Run: {run}. Why: {why}."
TEXT = {
    "order": HEAD + "\nIn your field: `git fetch origin {carrier}; git switch -C {branch} origin/{carrier}` (the train "
                    "with every car and fix so far, {base}), fix, commit, " + PUSH + PROOF + " Then answer "
                    "`done fixed <sha>` with the ack below (`tollman.py fixed` is run by the tollman, you only "
                    "answer).{proof} `{branch}` is a side branch: never landed on its own, it rides in this train; "
                    "after the barn merge it into your branch before /merge-from-main, then delete it (merge-to-main's "
                    "references/tollman.md, \"A fix order\"). `tollman.py triage {rid}` shows the evidence.{early}",
    "main": HEAD + "\nThe barn is red: a hand of yours fixes it in the train's worktree `{where}` on `{branch}` from {base} "
                   "(`git switch -C {branch} {base}`), commits, switches back to `{carrier}`, then you run "
                   "`tollman.py fixed main <sha> [--proof \"<the gate's green lines>\"]`; the fix rides in this train "
                   "(D29).{proof}",
    "early": " The run still runs: push your fix as soon as it is ready; the tollman merges it into the train after "
             "the run has finished.",
    "post": "tollman (wagon train): fix order {id} for field {field}: train {post} is in the barn, but {red} is red "
            "after its merge. Run: {run}.\nIn your field: `git fetch origin {carrier}; git switch -C {branch} "
            "origin/{carrier}` (the next train {train}, {base}), fix, commit, " + PUSH + PROOF + " Then answer "
            "`done fixed <sha>` with the ack below.{proof} `{branch}` is a side branch: never landed on its own, the "
            "tollman merges it into the next train before that train's run starts (nothing waits for it); after the "
            "barn merge it into your branch before /merge-from-main, then delete it. `tollman.py triage {rid}` shows "
            "the evidence.",
    "also": "tollman (wagon train): fix order {id} for field {field} also: {why}. Run: {run}. Fix it on the same "
            "branch `{branch}` before you answer `done fixed <sha>` for {id}; the run still runs.{proof}",
    "unpushed": "fix order {id}: field {field}'s fix {sha} sits on its local {branch}, not on origin, for over 30 "
                "min (L106: its pre-push refused the train's CHANGELOG commit?). Check it, then push it yourself "
                "(`HAL2_PRE_PUSH=0 git push origin {sha}:refs/heads/{branch}`) and run `tollman.py fixed {field} "
                "{sha}`.",
    "refused": "tollman (wagon train): your fix {sha} for fix order {id} is refused: {why}. The order stays open: "
               "branch `{branch}` from `origin/{carrier}`, fix, push and answer `done fixed <sha>` again.",
    "light": " The tollman runs {light} itself on your sha and takes the fix only green.",
    "heavy": " For {heavy} add the line the gate prints when the job is green on your commit (`code/bash/scripts/gate/"
             "main.sh <job> --branch origin/main`): `done fixed <sha>: gate: <job> green at <sha>`.",
}


def proof_text(top: str, jobs: list[str]) -> str:
    """What the order's message says the answer's proof is (fix_proof.py)."""
    light = fix_proof.light_jobs(top)[1]
    mine, heavy = [j for j in jobs if j in light], [j for j in jobs if j not in light]
    return (TEXT["light"].format(light=", ".join(mine)) if mine else "") + (
        TEXT["heavy"].format(heavy=", ".join(heavy) or "the red job") if heavy or not jobs else "")
