"""The strict-gain gate (plan 0390 step 2): a candidate replaces the incumbent only when its validation mean is
strictly greater; a tie is rejected (research 0100, SkillOpt's gate). Stdlib only.

`decide(candidate, incumbent)` takes two validation means, each a number or a judge.judge_split dict, and returns

    {"accept": bool, "margin": float (candidate - incumbent), "candidate": float, "incumbent": float, "reason": str}

A margin below `EPSILON` (float noise of a mean) counts as a tie.
"""

EPSILON = 1e-9


def mean_of(score):
    return float(score["mean"] if isinstance(score, dict) else score)


def decide(candidate, incumbent):
    cand, inc = mean_of(candidate), mean_of(incumbent)
    margin = cand - inc
    if margin > EPSILON:
        reason = f"accepted: validation {inc:.3f} -> {cand:.3f}"
    elif margin < -EPSILON:
        reason = f"rejected: validation fell {inc:.3f} -> {cand:.3f}"
    else:
        reason = f"rejected: no gain (a tie at {inc:.3f})"
    return {"accept": margin > EPSILON, "margin": margin, "candidate": cand, "incumbent": inc, "reason": reason}
