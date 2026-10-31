#!/usr/bin/env python3
"""The light checks a car's proof adds for the gate jobs its crop reaches (hal2 plan 0490 step 8).

Each runs only when the crop touches its inputs, so a crop that touches none starts no new process (D9); each
answers proof.py's `(exit, text)`: 0 green, 1 red with `<path>: ...` lines (proof.findings keeps the crop's clean
paths), any other exit skipped (never a red car: the landing's gate still runs it).

  keys               proof_keys.check (L61): a crop changing a plugin manifest or app-keys.json; no build
  skills             a plugin's `scripts/check-plugins.py` (gate job agents-test, L100): a crop changing a plugin's
                     `skills/**/SKILL.md` or `aliases.json`; its errors land on the crop's first such file
  env-readers,       python-lint's ceiling counts (L102): only when a crop file holds a line the field's own counter
  state-roots-count  counts (read from disk) and the crop's diff adds such a line (one `git diff -U0`); a red names
                     those files
  nodes              hal2-hub-core's NODE_PACKAGES (L119): a crop touching `code/protobuf/hal2/<pkg>/` with a
                     `hal2-<pkg>-node` crate whose `"hal2.<pkg>.` neither the field's nor the barn's routes.rs lists
  state              `hal2-cli-state check` (gate job records-check, L126): a crop touching `access.toml` or
                     `hal2-plugin.toml`; its exit 10 (problems) is a finding, one in the crop's own declaration is
                     the car's
"""

import importlib.util
import re
import sys
from pathlib import Path

import own_cli
import proof_keys

SKILLS = re.compile(r"^(code/agents/apps/[^/]+)/(skills/.+/SKILL\.md|aliases\.json)$")
PROTO = re.compile(r"^code/protobuf/hal2/([^/]+)/")
STATE = re.compile(r"(^|/)(access\.toml|hal2-plugin\.toml)$")
ROUTES = "code/rust/libs/hal2-hub-core/src/gate/routes.rs"
CEILINGS = {"env-readers": "code/python/scripts/env-readers/main.py",
            "state-roots-count": "code/python/scripts/state-roots-count/main.py"}
STATE_CLI = "hal2-cli-state"


def by_path(files: list[str]) -> list[str]:
    """The checks the crop's paths call for (the ceilings need the files' text: `ceilings`)."""
    wanted = {"keys": any(proof_keys.key_file(f) for f in files), "skills": any(SKILLS.match(f) for f in files),
              "nodes": any(PROTO.match(f) for f in files), "state": any(STATE.search(f) for f in files)}
    return [name for name, on in wanted.items() if on]


def counter(field: str, check: str):
    """The field's own ceiling counter as a module (no bytecode written), None when it has none."""
    path = Path(field) / CEILINGS[check]
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"proof_{check.replace('-', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    was, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001  (a counter that does not load is a check that cannot run)
        return None
    finally:
        sys.dont_write_bytecode = was
    return module


def counts(module, name: str, line: str) -> bool:
    """Whether the counter counts `line` of the file `name` (its own file filter and line test)."""
    skip = tuple(getattr(module, "OWNERS", ()) or getattr(module, "HELPERS", ()))
    if not name.startswith("code/") or name.endswith(".md") or name.startswith(skip):
        return False
    if getattr(module, "is_test", None) and module.is_test(name):
        return False
    test = getattr(module, "counted", None) or getattr(module, "LITERALS").search
    return bool(test(line))


def held(field: str, module, files: list[str]) -> list[str]:
    """The crop's files that hold a counted line on disk (no process)."""
    out = []
    for name in files:
        try:
            text = (Path(field) / name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(counts(module, name, line) for line in text.splitlines()):
            out.append(name)
    return out


def added(field: str, barn: str, head: str, names: list[str], run) -> dict[str, list[str]]:
    """{file: the lines the crop adds to it} of `names`, one `git diff -U0`."""
    code, text = run(["git", "diff", "-U0", "--no-color", "--no-renames", f"{barn}...{head}", "--", *names], field)
    out, name = {}, ""
    for line in text.splitlines() if code == 0 else []:
        if line.startswith("+++ "):
            name = line[6:] if line.startswith("+++ b/") else ""
        elif line.startswith("+") and name:
            out.setdefault(name, []).append(line[1:])
    return out


def ceilings(field: str, barn: str, head: str, files: list[str], run) -> dict[str, list[str]]:
    """{ceiling check: the crop's files whose added lines it counts}; a check with none is not wanted."""
    modules = {c: m for c in CEILINGS if (m := counter(field, c))}
    holding = {c: held(field, m, files) for c, m in modules.items()}
    names = sorted({n for got in holding.values() for n in got})
    if not names:
        return {}
    adds = added(field, barn, head, names, run)
    out = {}
    for c, got in holding.items():
        grew = [n for n in got if any(counts(modules[c], n, line) for line in adds.get(n, []))]
        if grew:
            out[c] = grew
    return out


def ceiling(check: str, field: str, grew: list[str], run) -> tuple[int, str]:
    """A ceiling counter's check in the field; red names the crop's files that add counted lines."""
    code, text = run(["python3", str(Path(field) / CEILINGS[check]), "check", "--root", field], field)
    if code != 1:
        return code, ""
    first = (text.splitlines() or [""])[0][:200]
    return 1, "\n".join(f"{name}: adds a line {check} counts and the count passes its ceiling ({first}); take the "
                        "value by its helper or name instead (L102)" for name in grew)


def skills(field: str, files: list[str], run) -> tuple[int, str]:
    """Each touched plugin's check-plugins; its error lines on the crop's first trigger file of that plugin."""
    first: dict[str, str] = {}
    for f in files:
        if m := SKILLS.match(f):
            first.setdefault(m[1], f)
    lines, judged = [], False
    for plugin, trigger in sorted(first.items()):
        script = Path(field) / plugin / "scripts" / "check-plugins.py"
        if not script.is_file():
            continue
        code, text = run(["python3", str(script)], field)
        if code not in (0, 1):
            continue
        judged = True
        errors = [ln.removeprefix("error: ").strip() for ln in text.splitlines() if ln.startswith("error:")]
        lines += [f"{trigger}: check-plugins: {e}" for e in errors] if code == 1 else []
    if not judged:
        return 127, ""
    return (1 if lines else 0), "\n".join(lines)


def folded(name: str) -> str:
    return name.replace("-", "").replace("_", "")


def nodes(field: str, barn: str, files: list[str], run) -> tuple[int, str]:
    """A node plugin's proto package missing from NODE_PACKAGES in both the field's and the barn's routes.rs."""
    crates = {folded(p.name[len("hal2-"):-len("-node")]) for p in (Path(field) / "code/rust/libs").glob("hal2-*-node")}
    first: dict[str, str] = {}
    for f in files:
        if (m := PROTO.match(f)) and folded(m[1]) in crates:
            first.setdefault(m[1], f)
    if not first:
        return 0, ""
    try:
        mine = (Path(field) / ROUTES).read_text(encoding="utf-8")
    except OSError:
        return 127, ""
    missing = {p: f for p, f in first.items() if f'"hal2.{p}.' not in mine}
    if missing:
        code, theirs = run(["git", "show", f"{barn}:{ROUTES}"], field)
        missing = {p: f for p, f in missing.items() if code != 0 or f'"hal2.{p}.' not in theirs}
    return (1 if missing else 0), "\n".join(
        f'{f}: the node plugin package hal2.{p} is not in NODE_PACKAGES of {ROUTES}: add "hal2.{p}." there '
        "(hub-core's every_method_has_a_route_and_an_action, L119)" for p, f in sorted(missing.items()))


def state(field: str, barn: str, head: str, run, build_run) -> tuple[int, str]:
    """`hal2-cli-state check` in the field (the candidate's own build when `.hal/own-cli.sh` names one); exit 10 =
    problems, whose `<path>: ...` lines are findings."""
    cli = own_cli.resolve(field, STATE_CLI, barn, head, build_run)
    if not cli:
        return 127, ""
    code, text = run([cli, "check"], field)
    return {0: 0, 10: 1}.get(code, code), text


def check(name: str, field: str, barn: str, head: str, files: list[str], run, build_run, grew=None) -> tuple[int, str]:
    """One of this module's checks (`grew`: the ceiling check's files, from `ceilings`)."""
    if name == "keys":
        return proof_keys.check(field, barn, head, files, run)
    if name == "skills":
        return skills(field, files, run)
    if name == "nodes":
        return nodes(field, barn, files, run)
    if name == "state":
        return state(field, barn, head, run, build_run)
    return ceiling(name, field, grew or [], run)
