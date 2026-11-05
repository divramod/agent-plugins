"""The tollman's commands but `tick` (split out of tollman.py by hal2 plan 0610 step 9, small-files): tollman.py's
module doc names every one; each imports what it runs, so the timer's tick loads none of them."""

import json
import sys

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
from handlers import HANDLERS
import mtm_scan
import role_cli


def command(args, rest: list[str], cli) -> int:
    """Every command but `tick`; each imports what it runs. `cli`: the tollman.py module (its `status`, WIRING)."""
    status, wiring = cli.status, cli.WIRING
    if args.cmd == "checks":
        import checks_cli
        args.argv = rest
        return checks_cli.main(args, status, wiring)
    if args.cmd == "wagons":
        import wagons
        print(wagons.run(args.repo, do_fetch=not args.no_fetch, as_json=args.json))
        return 0
    if args.cmd == "start-check":
        return role_cli.print_start_check(*role_cli.start_check(args.repo, wiring), args.json)
    if args.cmd == "status":
        s = status(args.repo)
        import status_cmd
        print(json.dumps(s, indent=1)) if args.json else status_cmd.show(s)
        return 0
    import hold
    import modes
    if args.cmd == "triage":
        import triage_cli
        return triage_cli.main(args)
    if args.cmd in hold.VERBS:
        return hold.main(args)
    if args.cmd in modes.VERBS:
        return modes.main(args)
    if args.cmd in ("order", "fixed"):
        import orders_cli
        return orders_cli.main(args, wiring)
    if args.cmd.startswith("resolve"):
        import resolve
        return resolve.main(args, wiring)
    if args.cmd in ("join", "cars"):
        import train_join
        return train_join.main(args)
    if args.cmd == "train":
        import trains_dry
        d = trains_dry.dry_run(args.repo)
        print(json.dumps(d, indent=1)) if args.json else trains_dry.print_dry_run(d)
        return 0
    if args.cmd in ("unhitch", "retry"):
        import engine_car
        code, text = (engine_car.unhitch(args.repo, args.field, args.why, user=args.by_user) if args.cmd == "unhitch"
                      else engine_car.retry(args.repo, args.why, skip_pretest=args.skip_pretest))
        print(text, file=sys.stderr if code else sys.stdout)
        return code or (go_on(args.repo, wiring) if args.cmd == "unhitch" else 0)
    if args.cmd == "chain":
        import chain
        code, text = chain.run(args.repo, wiring, HANDLERS["duty:trains"], args.in_tick)  # its import retried (L135)
        print(text)
        return code
    if args.cmd in ("silence", "unsilence"):
        import silence
        return silence.run(args, wiring, args.cmd == "silence")
    if args.cmd in ("act", "handoff"):  # each red job's fix order checked, every act and handoff (red_orders.py)
        if clash := handoff_clash(args, wiring):
            print(clash, file=sys.stderr)
            if args.cmd == "handoff":
                return 1
        code = (role_cli.run_wake if args.cmd == "act" else role_cli.run_handoff)(args, wiring)
        if not getattr(args, "json", False) and not (args.cmd == "act" and args.done is not None):
            __import__("red_orders").report(args.repo)
        return code
    if args.cmd == "timer":
        return role_cli.run_timer(args, wiring)
    if args.cmd == "mode":
        if args.set:
            role_cli.set_mode(args.repo, wiring, args.set)
        print(role_cli.mode(args.repo, wiring))
        return 0
    raise SystemExit(f"tollman.py: unknown command {args.cmd}")


def handoff_clash(args, wiring) -> str:
    """handoff.md against the in-force learnings (learnings_clash.py, plan 0610 D20): `handoff --clear` refuses on a
    clash, `act` warns; "" without one (and for every other call)."""
    if not (args.cmd == "act" and not args.json and args.done is None or args.cmd == "handoff" and args.clear):
        return ""
    import handoff
    import learnings_clash
    f = handoff.path(mtm_scan.main_checkout(args.repo), wiring)
    return learnings_clash.guard(f, f.parent)


def go_on(repo: str, wiring) -> int:
    """After the user's unhitch: a red train split by it is broken up and the rest formed again in this call (cause
    C); the session's unhitch of a car was refused before (plan 0360 D3)."""
    import board
    import chain
    import train_state
    train = train_state.standing(train_state.lines(mtm_scan.main_checkout(repo)))
    if not train or train["state"] != "split":
        return 0
    code, text = chain.run(repo, wiring, HANDLERS["duty:trains"])
    print(text)
    board.safely(mtm_scan.main_checkout(repo), "messages and acks", board.sync)
    return code
