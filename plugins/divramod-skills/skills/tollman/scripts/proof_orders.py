"""A car with red light gate checks rides and is fixed in the train (the user, 2026-11-04, angry: "i told you at
least 20 times, to take all finished ones into the train"). Before, `trains.draft` unhitched such a wagon; now it is
a car with `proof_red` (proof.py's finding lines), and:

- `red_line` (engine.restart before every start, open_train.stops before a push): a car with `proof_red` and no fix
  order of this train yet (it formed so, or joined so: plan 0610 E5; a red join pretest adds `pretest_red`, E6) makes
  the train red before its landing starts or pushes, status `proof_red` (STATUS), so nothing is pushed while a light
  check is red;
- `actions` (trains.plan, each round while a train is `red` or `fixing`, whatever its red): per such car its fix order
  by code, `tollman.py order <car> --why "proof: ..." --job <gate job>` (orders.py through red_claims.py: an acked
  message, the fix on `<NN>-train-<n>-<a>-fix` from `origin/train-<n>-<a>` (run_names.py), answered `done fixed
  <sha>`, merged into the carrier
  by `fixed`); cars whose finding text is the same get one order, to the first of them, and a board note to the
  farmer names the others (NOTE, board.NOTES). The last order fixed, the train is `retry` and its landing starts
  with every car and fix: the push waits for these orders as for any open order, the car is never dropped.
"""

import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import train_state
from tick import act

STATUS = "proof_red"
NOTE = "proof-twin"  # the board note's kind (board.NOTES)
CLI = Path(__file__).with_name("tollman.py")
WEEK = 7 * 24 * 3600
JOBS = {"names": "python-lint", "env-readers": "python-lint", "state-roots-count": "python-lint",
        "records": "records-check", "state": "records-check", "skills": "agents-test"}  # proof.py's check: gate job


def red_cars(train: dict) -> list[dict]:
    return [c for c in train.get("cars") or [] if c.get("proof_red")]


def ordered(rows: list[dict], name: str) -> set[str]:
    """The fields the train `name` has placed a fix order for (open or fixed)."""
    return {e.get("field") for e in rows if e.get("kind") == "order" and e.get("train") == name}


def red_line(main: str, field: str, train: dict, now=None) -> str:
    """The `red` line of a train about to start (or push) with a car whose light checks are red and that has no fix
    order of this train yet (one that formed so, or joined so: plan 0610 E5, E6), its text; "" when it has none."""
    done = ordered(train_state.lines(main), train["train"])
    red = [c for c in red_cars(train) if c["field"] not in done]
    if not red:
        return ""
    why = "light gate checks red: " + "; ".join(f"{c['field']}: {c['proof_red'][0]}" for c in red)
    train_state.append(main, "red", field, now, train=train["train"], status=STATUS, why=why[:600])
    return (f"train {train['train']} is red before its landing ({why[:200]}): each such car gets its fix order in "
            "the train, the landing starts once they are fixed")


def jobs_of(lines: list[str]) -> list[str]:
    """The gate jobs the finding lines' checks (`<check>: ...`) belong to, in order, once."""
    return list(dict.fromkeys(JOBS[c] for c in (ln.split(":", 1)[0].strip() for ln in lines) if c in JOBS))


def actions(top: str, main: str, train: dict, rows: list[dict]) -> list[dict]:
    """Each red car's fix order (one per distinct finding text) and the twins' board note; none twice."""
    name = train["train"]
    done, out, first = ordered(rows, name), [], {}
    for car in red_cars(train):
        field, text = car["field"], "\n".join(car["proof_red"])
        if text in first:
            out.append(act("trains", NOTE, "record", mtm_scan.roles.slot_name(main), key=f"{NOTE}:{name}:{field}",
                           window=WEEK, text=f"train {name}: car {field}'s light checks are red with the same "
                           f"findings as car {first[text]}'s: one fix order went to {first[text]}, none to {field}"))
            continue
        first[text] = field
        if field in done:
            continue
        why = f"proof: light gate checks red on {car['head'][:12]}: " + "; ".join(car["proof_red"])
        jobs = list(dict.fromkeys(jobs_of(car["proof_red"]) + list(car.get("pretest_red") or [])))  # a join's pretest
        argv = [sys.executable, str(CLI), "order", field, "--why", why[:600],
                *[a for j in jobs for a in ("--job", j)], "--repo", top]
        stuck = act("trains", "train-red", "wake", key=f"proof-order:{name}:{field}:failed",
                    text=f"train {name}: the fix order for car {field}'s red light checks failed "
                         f"(`{' '.join(argv[1:4])} ...`); place it by hand: {why[:300]}")
        out.append(act("trains", "proof-order", "run", field, key=f"proof-order:{name}:{field}", window=WEEK,
                       argv=argv, on_fail=[stuck], text=f"train {name}: fix order to {field} for its red light checks"))
    return out
