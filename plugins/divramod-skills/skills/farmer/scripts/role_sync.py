"""The sync duty's rule as code: the farmer branch's role file (roles/farmer/ROLE.md) reaches main, so main and the
farmer branch (`farmer-<project>`, hal2 .adr/roles-folder.md) stay alike.

The farmer commits the user's role file edits on its own branch and merges main into it every round, but its
commits reach main only through a landing. When main's role file differs from the farmer branch's, one servant
is told directly (no plan): merge the latest main, then the latest farmer branch, then land it (/mtm), as the
merge-to-main boss's "land now". The farmer merges the new main back in its next round (the frame's stay-current).
"""

from pathlib import Path

import delegation
import roles
from tick import ROLE, act, default_ref, git

KEY = "sync:"
TITLE = "Land the farmer branch's roles/farmer/ROLE.md on main"
PROMPT = ("merge-to-main boss: land now. You are a servant started by the farmer (the user's stand-in for {repo}): read "
          "your role at {role} first; the user will not answer questions, so never ask any. The farmer branch holds "
          "roles/farmer/ROLE.md changes that main lacks (brief: {brief}). Write `farmer-sync` into plans/CURRENT_PLAN, then: "
          "1. /mfm (the latest main into your slot, also when your session just ran it: main may have moved); "
          "2. `git merge --no-edit {farmer_slot}` (the latest farmer branch; it may change roles/farmer/ only: when its merge "
          "brings anything else, abort it and message the farmer session in one line); 3. /mtm. This land-now counts "
          "as the user's own /mtm (the farmer's authority, 2026-10-03). No plan for this. Ack every farmer "
          "instruction; when you are blocked, message the farmer session with one line.")
ROLE_TASK = ("- Task: merge the latest main, then the latest farmer branch (roles/farmer/ROLE.md only) into your slot and "
             "land it with /mtm, as the prompt says. No plan.")


def role_state(top: str) -> dict:
    """Whether main's role file differs from the farmer branch's committed one, and the farmer branch's head."""
    mine, main = git(top, "show", f"HEAD:{ROLE}"), git(top, "show", f"{default_ref(top)}:{ROLE}")
    return {"differs": bool(mine) and mine != main, "sha": git(top, "rev-parse", "--short", "HEAD")}


def plan_sync(item: dict, ctx: dict, state: dict | None = None, held: dict | None = None) -> list[dict]:
    state = state if state is not None else role_state(ctx["top"])
    if not state.get("differs"):
        return []
    held = held if held is not None else delegation.ledger(ctx["main"])
    if any(k.startswith(KEY) and e.get("state") in ("running", "waiting") for k, e in held.items()):
        return []  # one sync at a time: it lands whatever the farmer branch holds when it merges
    branch = roles.slot_name(ctx["main"])
    brief = {"farmer_head": state["sha"], "farmer_branch": branch, "file": ROLE, "repo": Path(ctx["main"]).name}
    return [act("sync", "farmer-ahead", "delegate", "-", key=KEY + state["sha"], text=TITLE, prompt=PROMPT,
                role_task=ROLE_TASK, brief=brief,
                task=f"Merge the latest main, then the latest `{branch}` branch, into your slot and land it with /mtm.",
                done=f"main's {ROLE} equals the farmer branch's (`git diff --quiet origin/main {branch} -- {ROLE}`).")]
