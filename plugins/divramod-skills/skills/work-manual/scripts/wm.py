#!/usr/bin/env python3
"""work-manual (hal2 plan 0595 step 5): the open manual items of every farm on the machine, listed, shown and ticked
off through `hal2-cli-plans manual` (the one writer of the items; this script never reads or writes a plan file).

  wm.py list [--json]   every farm's open items by farm and plan, a line each: id, title, what waits
  wm.py show <id>       one item: why, steps (the guide) and done-when, as stored
  wm.py done <id>       mark it done (`manual done`), only on the user's word

An id is `<farm>/<NNNN>/<NN>`. The farms are hal2's own rule: the repositories directly under git.toml's `root`
(default `<home>/a`) that have a `plans/` folder; home is $HAL2_HOME else $HOME, the config folder $HAL2_CONFIG_DIR
else hal2's config folder under the home (the names hal2_core::paths reads). The CLI is $HAL2_CLI_PLANS, else hal2-cli-plans on PATH.
A farm whose CLI call fails is a `problem:` line, never a stop. Exit 0, 1 an item or farm not found or the CLI failed
(`done`), 2 bad arguments or no CLI.
"""
import json
import os
import re
import subprocess
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCHEMA = 1
ID = re.compile(r"^([^/\s]+)/(\d{4})/(\d{2,})$")


def home() -> Path:
    return Path(os.environ.get("HAL2_HOME") or Path.home())


def config_dir() -> Path:
    return Path(os.environ.get("HAL2_CONFIG_DIR") or home() / ".config" / "hal2")


def farm_root() -> Path:
    """git.toml's `root` (a leading `~/` is the home), else `<home>/a`."""
    try:
        root = tomllib.loads((config_dir() / "git.toml").read_text()).get("root")
    except (OSError, tomllib.TOMLDecodeError):
        root = None
    if not isinstance(root, str) or not root:
        return home() / "a"
    return home() / root[2:] if root.startswith("~/") else Path(root)


def farms() -> list[Path]:
    """The repositories under the root that have a `plans/` folder, sorted by name."""
    try:
        entries = sorted(farm_root().iterdir())
    except OSError:
        return []
    return [p for p in entries if not p.name.startswith(".") and (p / ".git").exists() and (p / "plans").is_dir()]


def cli() -> str:
    return os.environ.get("HAL2_CLI_PLANS") or "hal2-cli-plans"


def run_cli(args: list[str]) -> tuple[int, str, str]:
    try:
        done = subprocess.run([cli(), *args], capture_output=True, text=True, check=False)
    except OSError as err:
        return 127, "", f"{cli()}: {err.strerror or err}"
    return done.returncode, done.stdout, done.stderr.strip()


def farm_items(farm: Path, state: str) -> tuple[list[dict], list[str]]:
    """The farm's manual items in `state` (open, done, all) and its problems (the CLI's, as lines)."""
    code, out, err = run_cli(["manual", "list", "--farm", "--state", state, "--json", "--repo", str(farm)])
    if code != 0:
        why = (err or out).strip().splitlines()
        return [], [f"{farm.name}: hal2-cli-plans manual list failed (exit {code}): {why[0] if why else 'no output'}"]
    try:
        doc = json.loads(out)
        items = list(doc["items"])
        problems = [f"{farm.name}: {p.get('file', '?')}: {p.get('message', '?')}" for p in doc.get("problems", [])]
    except (ValueError, KeyError, TypeError, AttributeError):
        return [], [f"{farm.name}: hal2-cli-plans manual list printed no JSON items"]
    return items, problems


def all_farms(state: str) -> list[tuple[Path, list[dict], list[str]]]:
    found = farms()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda farm: farm_items(farm, state), found))
    return [(farm, items, problems) for farm, (items, problems) in zip(found, results)]


def line(item: dict) -> str:
    waits = f"  (waits: {item['waits']})" if item.get("waits") else ""
    return f"{item['id']}  {item['title']}{waits}"


def cmd_list(args: list[str]) -> int:
    as_json = "--json" in args
    rest = [a for a in args if a != "--json"]
    if rest:
        return usage(f"list: unknown argument {rest[0]!r}")
    groups = all_farms("open")
    problems = [p for _, _, found in groups for p in found]
    shown = [(farm, items) for farm, items, _ in groups if items]
    if as_json:
        farms_out = [{"farm": farm.name, "path": str(farm), "items": items} for farm, items in shown]
        print(json.dumps({"schema": SCHEMA, "farms": farms_out, "problems": problems}, indent=2))
        return 0
    total = 0
    for farm, items in shown:
        print(f"{farm.name}")
        plans: dict[str, list[dict]] = {}
        for item in items:
            plans.setdefault(item["slug"], []).append(item)
        for slug in sorted(plans):
            print(f"  {slug}")
            for item in sorted(plans[slug], key=lambda i: i["n"]):
                print(f"    {line(item)}")
                total += 1
    for problem in problems:
        print(f"problem: {problem}")
    noun = "item" if total == 1 else "items"
    print(f"{total} open manual {noun} in {len(shown)} of {len(groups)} farms")
    return 0


def split_id(args: list[str], verb: str) -> tuple[str, str] | int:
    if len(args) != 1:
        return usage(f"{verb}: one id <farm>/<NNNN>/<NN>")
    match = ID.match(args[0])
    if not match:
        return usage(f"{verb}: {args[0]!r} is not an id <farm>/<NNNN>/<NN>")
    return args[0], match.group(1)


def farm_path(name: str) -> Path | None:
    return next((farm for farm in farms() if farm.name == name), None)


def cmd_show(args: list[str]) -> int:
    parsed = split_id(args, "show")
    if isinstance(parsed, int):
        return parsed
    item_id, name = parsed
    farm = farm_path(name)
    if farm is None:
        print(f"no farm {name!r} with plans under {farm_root()}", file=sys.stderr)
        return 1
    items, problems = farm_items(farm, "all")
    for problem in problems:
        print(f"problem: {problem}")
    item = next((i for i in items if i.get("id") == item_id), None)
    if item is None:
        print(f"no manual item {item_id}", file=sys.stderr)
        return 1
    print(f"{item['id']}  {item['title']}")
    head = [f"state: {item['state']}", f"plan: {item['slug']}"]
    if item.get("from"):
        head.append(f"from: Q{item['from']}")
    if item.get("waits"):
        head.append(f"waits: {item['waits']}")
    print("  ".join(head))
    for title, key in (("Why", "why"), ("Steps", "steps"), ("Done when", "done_when")):
        print(f"\n## {title}\n{(item.get(key) or '').rstrip()}")
    for extra in item.get("extra") or []:
        print(f"\n## {extra.get('name', '')}\n{(extra.get('text') or '').rstrip()}")
    return 0


def cmd_done(args: list[str]) -> int:
    parsed = split_id(args, "done")
    if isinstance(parsed, int):
        return parsed
    item_id, name = parsed
    farm = farm_path(name)
    if farm is None:
        print(f"no farm {name!r} with plans under {farm_root()}", file=sys.stderr)
        return 1
    code, out, err = run_cli(["manual", "done", item_id, "--repo", str(farm)])
    if out.strip():
        print(out.rstrip())
    if code != 0:
        print(err or f"hal2-cli-plans manual done failed (exit {code})", file=sys.stderr)
        return 2 if code == 127 else 1
    return 0


def usage(message: str = "") -> int:
    if message:
        print(message, file=sys.stderr)
    print(__doc__.split("\n\n")[0].strip(), file=sys.stderr)
    return 2


def main(argv: list[str]) -> int:
    commands = {"list": cmd_list, "show": cmd_show, "done": cmd_done}
    if not argv or argv[0] in ("-h", "--help", "h"):
        print(__doc__.strip())
        return 0
    if argv[0] not in commands:
        return usage(f"unknown command {argv[0]!r}")
    return commands[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
