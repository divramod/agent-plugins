"""`tollman.py triage [<run>] [--json]` (hal2 plan 0360 step 5, D5): the triage of a train's land run for the session,
the same evidence its wake carries (triage.py). Without a run: the standing train's, its current start's run
(watch.py's `run` line) or else its red line's run."""

import json

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import train_state
import triage


def add_parser(sub) -> None:
    p = sub.add_parser("triage")
    p.add_argument("run", nargs="?", help="the land run's id or address; default: the standing train's")
    p.add_argument("--json", action="store_true")


def target(main: str, run: str | None) -> tuple[dict | None, str | None]:
    """(the standing train, the run's address or bare id) for `run` or the train's own run."""
    train = train_state.standing(train_state.lines(main))
    return train, run or (train or {}).get("land_run") or (train or {}).get("run")


def lines(verdict: dict) -> list[str]:
    """The verdict as text: its kind, then each piece of evidence."""
    out = [f"triage: {verdict['kind']}"]
    for key, value in verdict["evidence"].items():
        if key == "cars":
            out += ["cars' files against the train's base:"] + [f"  {c['field']}: {', '.join(c['files']) or 'no file'}"
                                                                 for c in value]
        elif key == "tail":
            out += ["log tail:", value]
        else:
            out.append(f"{key}: {', '.join(value) if isinstance(value, list) else value}")
    return out


def main(args) -> int:
    main_dir = mtm_scan.main_checkout(args.repo)
    train, url = target(main_dir, args.run)
    if not url:
        print("no run to triage: no train stands with a land run; name one (`tollman.py triage <run>`)")
        return 1
    verdict = triage.of(args.repo, train or {"cars": []}, url)
    if not verdict:
        print(f"no run to triage at {url}")
        return 1
    print(json.dumps(verdict, indent=1)) if args.json else print("\n".join(lines(verdict)))
    return 0
