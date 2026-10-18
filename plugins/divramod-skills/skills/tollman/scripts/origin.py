"""The origin trailers of a commit the tollman writes (hal2 plan 0355, D2): `Worktree: <NN>` (a train: every car's
field, `Worktree: 02, 03, 27`) and, for a car on a plan, `Plan: <NNNN>-<slug>`. The subject says what changed; these
lines are the message's last paragraph, before any attribution. A plan name that is no `<NNNN>-<slug>` (a shot's
`<shotfile>/<n>/<title>`) has no `Plan:` line."""
import re

PLAN = re.compile(r"^\d{4}-[a-z0-9][a-z0-9-]*$")


def trailers(fields: list[str], plans: list[str] | tuple = ()) -> str:
    """The trailer paragraph of the fields (in car order) and the plans among `plans` that are plan names."""
    lines = ["Worktree: " + ", ".join(dict.fromkeys(fields))] if fields else []
    lines += [f"Plan: {p}" for p in dict.fromkeys(plans) if PLAN.match(p or "")]
    return "\n".join(lines)


YARD = "main"  # the yard (the main checkout's uncommitted work) is `main` in the landing's trailer too (hal2-git title.rs)
