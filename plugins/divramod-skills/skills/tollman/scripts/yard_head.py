"""The yard's commits as the train's first car (hal2 plan 0789 D2): the steward may commit everything in the yard and
pull the barn in with a merge, so the yard stands ahead of the barn. Its HEAD then rides as one merge in the carrier,
before the yard's uncommitted files (yard.carry); after the green landing the barn holds it and yard.settle's
`pull --ff-only` fast-forwards the yard. No reset, no stash, the yard's commits never rewritten.

  ahead(yard, default)            the yard's HEAD when it holds commits the barn lacks, else None
  judge(yard, base, default, ...) whether that HEAD may ride onto the carrier's `base`: {"head", "merge" (the trial
                                  merge's commit, the base yard.sort weighs the uncommitted files on), "paths" (what
                                  the yard's commits change), "why"}. It stays out, said, never forced, when a path
                                  its commits change is refused (refused: yard_rules' secret-shaped, junk, a root
                                  outside the allowlist; a line break, a submodule, larger than 5 MB), when it is the
                                  head a session unhitched from a red train, when it does not merge cleanly onto the
                                  base (a yard not based on the barn is said so) or a car would not merge onto it
  merge(field, yard, head)        the head merged into the tollman's field (`git merge --no-ff`, hooks on); fetched
                                  from the yard first when the field's object store lacks it

`ahead` and `judge` only read the yard (a trial merge writes a dangling commit into the shared object store, as
trial.merge does in the field); the yard itself changes only in yard.settle.
"""

from __future__ import annotations

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)

import origin
import trial
import yard
import yard_rules as rules

SUBJECT = "chore(yard): the yard's commits up to {short}"
BODY = "Brought in by the tollman from the main checkout's commits, as the train's first car (hal2 plan 0789 D2)."
BODY_NEUTRAL = "Brought in from the main checkout's commits, as the train's first car."
SHOWN = 3


def ahead(repo: str, default: str) -> str | None:
    """The yard's HEAD when it has commits `default` lacks; None when the barn holds it (or git cannot say)."""
    count = yard.run(repo, "rev-list", "--count", f"{default}..HEAD").stdout.strip()
    return yard.run(repo, "rev-parse", "HEAD").stdout.strip() or None if count not in ("", "0") else None


def sizes(repo: str, rev: str, paths: list[str]) -> dict[str, tuple[str, int]]:
    """{path: (type, size)} of what `rev` holds at the paths, in one `git cat-file`; a path it lacks is left out."""
    paths = [p for p in paths if "\n" not in p]
    said = yard.run(repo, "cat-file", "--batch-check=%(objecttype) %(objectsize)",
                    data="".join(f"{rev}:{p}\n" for p in paths)).stdout.split("\n") if paths else []
    found = {p: line.split(" ") for p, line in zip(paths, said)}
    return {p: (o[0], int(o[1])) for p, o in found.items() if len(o) == 2 and o[1].isdigit()}


def refused(repo: str, base: str, head: str, paths: list[str]) -> list[dict]:
    """[{path, why}] of the paths the yard's commits change that may not ride: yard_rules' names against the root
    allowlist as `head` holds it, and the file itself as `head` holds it. A deletion is judged by nothing."""
    record = yard.run(repo, "show", f"{head}:{rules.RECORD}").stdout
    roots = rules.allowlist(record) | {n for n in yard.run(repo, "ls-tree", "--name-only", "-z", base).stdout.split("\0")
                                       if n}
    barn, there = yard.objects(repo, base, paths), sizes(repo, head, paths)
    dirs = sorted({j.rstrip("/") for j in map(rules.junk, paths) if j and j.endswith("/")})
    tracked, out = set(yard.objects(repo, base, dirs)), {}
    for path in paths:
        if "\n" in path:
            out.setdefault(path, "a line break in its name")
            continue
        if path not in there:
            continue
        kind, size = there[path]
        found = rules.named(path, path in barn, roots, tracked) or (
            path, "a submodule or a nested repository" if kind == "commit"
            else f"larger than 5 MB ({size / 1048576:.1f} MB)" if size > yard.MAX else None)
        if found[1]:
            out.setdefault(*found)
    return [{"path": p, "why": w} for p, w in out.items()]


def named(items: list[dict]) -> str:
    more = f"; {len(items) - SHOWN} more" if len(items) > SHOWN else ""
    return "; ".join(f"{x['path']} ({x['why']})" for x in items[:SHOWN]) + more


def judge(repo: str, base: str, default: str, cars: list[dict] | tuple = (), past: dict | None = None) -> dict:
    """Whether the yard's HEAD rides onto `base` (see the module); `why` empty: it rides, or the yard is not ahead
    (`head` None). `cars`: the train's ([{field, head}]), `past`: train_fold.yard_past's."""
    out = {"head": None, "merge": None, "paths": [], "why": ""}
    head = ahead(repo, default)
    if not head:
        return out
    short = head[:10]
    if (past or {}).get("refused_head") == head:
        return {**out, "why": f"the yard's commits up to {short} were unhitched from a red train: they stay until "
                              "the yard's head changes"}
    diff = yard.run(repo, "diff", "--name-only", "--no-renames", "-z", f"{base}...{head}").stdout
    paths = sorted(p for p in diff.split("\0") if p)
    bad = refused(repo, base, head, paths)
    if bad:
        return {**out, "why": f"the yard's commits up to {short} change {len(bad)} path{'s' * (len(bad) != 1)} "
                              f"that may not ride: {named(bad)}; the commits are never rewritten"}
    merged, files = trial.merge(repo, base, head)
    if merged is None or files:
        based = yard.run(repo, "merge-base", "--is-ancestor", default, head).returncode == 0
        why = "the trial merge could not run" if merged is None else f"it conflicts ({', '.join(files[:SHOWN])})"
        return {**out, "why": f"the yard's commits up to {short}"
                              + ("" if based else f" (not based on {default})") + f" do not merge onto the train: {why}"}
    acc = merged
    for car in cars:
        acc, files = trial.merge(repo, acc, car["head"])
        if acc is None or files:
            return {**out, "why": f"car {car['field']} would not merge onto the yard's commits up to {short} "
                                  f"({', '.join(files[:SHOWN])})"}
    return {"head": head, "merge": merged, "paths": paths, "why": ""}


def merge(field: str, repo: str, head: str) -> tuple[str | None, str]:
    """The yard's `head` merged into the field: (the merge commit, "") or (None, why) and the field as it was."""
    if yard.run(field, "cat-file", "-e", f"{head}^{{commit}}").returncode:  # a field that shares no objects
        yard.run(field, "fetch", "-q", "--no-tags", repo, "HEAD")
        if yard.run(field, "cat-file", "-e", f"{head}^{{commit}}").returncode:
            return None, f"the yard's head {head[:10]} could not be fetched into the field"
    body = BODY_NEUTRAL if origin.neutral(field) else BODY
    done = yard.run(field, "merge", "-q", "--no-ff", "--no-edit", "-m", SUBJECT.format(short=head[:10]), "-m", body,
                    *origin.paragraph(field, [origin.YARD]), head)
    if done.returncode:
        yard.run(field, "merge", "--abort")
        return None, (done.stderr or done.stdout).strip()[-300:] or "git merge failed"
    return yard.run(field, "rev-parse", "HEAD").stdout.strip(), ""
