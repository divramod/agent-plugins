"""`tollman.py order` and `tollman.py fixed` (hal2 plan 0360 step 6; orders.py): the verbs run in the tollman's field,
their message or wake done at once by the frame's `tick.execute` (stamped with an ack id, logged under its key, so
no round sends it again), wakes handed to the session's wake.json as a round's (`wake.hand_over`).

  tollman.py order <field>|main --why <text> [--run <url>] [--job <gate job>]... [--smuggle] [--post <train>]
                   [--repo <dir>]
  tollman.py fixed <field>|main <sha> [--proof <the answer's green lines>] [--unproven <why>] [--repo <dir>]
  tollman.py fixed <field> --redundant [--repo <dir>]    its fix is in the train already (L56)

`main` with no train standing is own_fix.py's: the fix becomes the first car of the next train (plan 0360 step 8).
`--smuggle`: the field is a smuggle's, no car (a resume conflict or a smuggled red, smuggled.py, plan 0360 step 18).
`--post <train>`: a car of that landed train is red after its merge; the order rides the train that stands, never
holds it (post_merge.py, plan 0383 step 6).
`--job`: a gate job the fix must turn green (else those the `--why` or the train's red names); `fixed` takes the sha
only proven green: a light job run here on it, a heavy one by the red check's `green: <check> at <sha>` line in `--proof` (plan 0610 D6; a gate line also counts);
`--unproven <why>` is the session's word without proof (fix_proof.py, plan 0522 D5).
"""

import datetime as dt

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import foreman_wake
import mtm_scan
import orders
import roletime
import own_fix
import red_claims
import tick
import train_state
import train_wt
import wake


def add_parser(sub) -> None:
    o = sub.add_parser("order")
    o.add_argument("field")
    o.add_argument("--why", required=True)
    o.add_argument("--run")
    o.add_argument("--smuggle", action="store_true", help="the field smuggled; it rides no car (plan 0360 step 18)")
    o.add_argument("--post", help="the landed train whose run is red after its merge (plan 0383 step 6)")
    o.add_argument("--job", action="append", default=[], help="a gate job the fix must turn green (plan 0522 D5)")
    o.add_argument("--unit", action="append", default=[],
                   help="the failing test or file this order is for: one red, one foreman (red_claims.py)")
    f = sub.add_parser("fixed")
    f.add_argument("field")
    f.add_argument("sha", nargs="?")
    f.add_argument("--proof", default="", help="the answer's text: its `green: <the red check> at <sha>` lines")
    f.add_argument("--unproven", default="", help="the session's why for taking the fix without proof")
    f.add_argument("--redundant", action="store_true",
                   help="its fix is in the train already: closed on the carrier's head (L56)")


def deliver(top: str, main: str, actions: list[dict], ctx: dict, wiring) -> None:
    """The verb's actions done as a round does them (chain.link's way); an order to a field without a session
    starts it first, a paused field's goes to the farmer (foreman_wake.py, plan 0522 D21)."""
    out: dict = {}
    for a in tick.fresh(foreman_wake.gate(actions, ctx), ctx["log"], ctx["now"], wiring.role):
        tick.execute(a, top, main, out, wiring)
    if any(out.get(k) for k in wake.KINDS):
        wake.hand_over(top, main, out, ctx["now"], wiring)


def main(args, wiring) -> int:
    main_dir = mtm_scan.main_checkout(args.repo)
    top = str(mtm_scan.roles.slot_dir(main_dir, wiring.role))
    ctx = tick.context(top, main_dir, {}, roletime.aware(), False, wiring)
    own = args.field == orders.MAIN and not train_state.standing(train_state.lines(main_dir))  # plan 0360 step 8
    carrier = train_wt.carrier(top)  # a car's fix merges into the train's worktree (plan 0375 D5)
    if args.cmd == "order":
        code, text, actions = (own_fix.order(top, args.why, args.run) if own else
                               red_claims.order(carrier, args.field, args.why, args.run, ctx["panes"],
                                                smuggle=args.smuggle, post=args.post, jobs=args.job, units=args.unit))
    else:
        if not (args.sha or args.redundant):
            print("fixed needs <sha> or --redundant")
            return 2
        code, text, actions = (own_fix.fixed(top, args.sha) if own else
                               orders.fixed(carrier, args.field, args.sha, ctx["panes"], proof=args.proof,
                                            unproven=args.unproven, redundant=args.redundant))
    deliver(top, main_dir, actions, ctx, wiring)
    print(text)
    return code
