"""The fix orders' message texts (orders.py, hal2 plan 0360 step 6): the order, the barn's own fix, the early and
post-merge words, a second red job (`also`, plan 0522 D16), a fix left local (L106), a refusal, and what the answer's
proof is (`proof_text`, fix_proof.py, plan 0522 D5)."""

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import fix_proof

# L84, L106: the side branch carries the train's generated commit (CHANGELOG.md), which a field's pre-push refuses
PUSH = "`HAL2_PRE_PUSH=0 git push origin {branch}` (the train's own CHANGELOG commit is no change of yours)."
# plan 0610 D6 (the user: "only what was red"; replaces L113's and L85's whole job): what a fix runs before it is
# answered, the red check in its smallest form; the triage's order says the same (run_triage_text.ORDER)
PROOF = (" Before you answer, run only what was red, in its smallest form: the failing test (`cargo nextest run -p "
         "<crate> -E 'test(<name>)'`, `bats -f <name> <file>`), the build, the one lint check or the CI step; never "
         "the whole gate job.")
# plan 0610 D18 (roles/tollman/ROLE.md): a fix is worked in the field's kept fix worktree, never its own checkout (it
# stays on its hitched head), on one systematic branch per field and run (run_names.py)
WHERE = ("In your kept fix worktree `{where}`, never your field's own checkout (it stays on its hitched head): "
         "`git fetch origin {carrier}; git -C {where} checkout -B {branch} origin/{carrier} || "
         "git worktree add -B {branch} {where} origin/{carrier}`")
HEAD = "tollman (wagon train): fix order {id} for field {field}: train {train} is red ({red}). Run: {run}. Why: {why}."
TEXT = {
    "order": HEAD + "\n" + WHERE + " (the train with every car and fix so far, {base}); fix, commit, " + PUSH + PROOF
             + " Then answer `done fixed <sha>` with the ack below (`tollman.py fixed` is run by the tollman, you only "
                    "answer).{proof} `{branch}` is a side branch: never landed on its own, it rides in this train; "
                    "after the barn merge it into your branch before /merge-from-main, then delete it (merge-to-main's "
                    "references/tollman.md, \"A fix order\"). `tollman.py triage {rid}` shows the evidence.{early}",
    "main": HEAD + "\nThe barn is red: a hand of yours fixes it in your kept fix worktree `{where}` on `{branch}` from "
                   "{base} (`git -C {where} checkout -B {branch} {base} || "
                   "git worktree add -B {branch} {where} {base}`; the carrier `{carrier}` is never switched), commits, "
                   "then you run "
                   "`tollman.py fixed main <sha> [--proof \"green: <the red check> at <sha>\"]`; the fix rides in this train "
                   "(D29).{proof}",
    "early": " The run still runs: push your fix as soon as it is ready; the tollman merges it into the train after "
             "the run has finished.",
    "post": "tollman (wagon train): fix order {id} for field {field}: train {post} is in the barn, but {red} is red "
            "after its merge. Run: {run}.\n" + WHERE + " (the next train {train}, {base}); fix, commit, " + PUSH + PROOF
            + " Then answer `done fixed <sha>` with the ack below.{proof} `{branch}` is a side branch: never landed on "
            "its own, the tollman merges it into the next train before that train's run starts (nothing waits for it); after the "
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
    "heavy": " For {heavy} add the red check's own green on your commit (the failing test, build, lint check or CI "
             "step that was red, never the whole job): `done fixed <sha>: green: <that check> at <sha>`.",
}


def proof_text(top: str, jobs: list[str]) -> str:
    """What the order's message says the answer's proof is (fix_proof.py)."""
    light = fix_proof.light_jobs(top)[1]
    mine, heavy = [j for j in jobs if j in light], [j for j in jobs if j not in light]
    return (TEXT["light"].format(light=", ".join(mine)) if mine else "") + (
        TEXT["heavy"].format(heavy=", ".join(heavy) or "the red job") if heavy or not jobs else "")
