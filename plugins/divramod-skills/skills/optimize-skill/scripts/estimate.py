"""The token estimate of one run before it starts (plan 0390 step 4; research 0100 "What one run costs"). No model call.

    rollouts    = (train + val) x (1 baseline + epochs x candidates)
    reflections = epochs, edit calls = epochs x candidates

times research 0100's processed tokens per call (rollout ~60k, reflection 65k, edit proposal 30k, llm.ESTIMATES),
an estimate within a factor of 2: turn count and skill size dominate. It is the worst case: early stops (train at
100%, two rejected epochs, the caps) only make a run cheaper. `fits` says whether the caps allow the whole run.
"""

import budget
import llm

ROLLOUT = 60_000
PER_CALL = {"rollout": ROLLOUT, "reflect": llm.ESTIMATES["reflect"], "edit": llm.ESTIMATES["edit"]}


def estimate(n_train, n_val, *, epochs=3, candidates=2, max_tokens=budget.DEFAULT_MAX_TOKENS,
             max_rollouts=budget.DEFAULT_MAX_ROLLOUTS, model="haiku", optimizer_model=llm.DEFAULT_MODEL):
    """The estimate dict: rows per call kind, the total, whether it fits the caps."""
    counts = {"rollout": (n_train + n_val) * (1 + epochs * candidates), "reflect": epochs,
              "edit": epochs * candidates}
    rows = [{"kind": kind, "count": count, "each": PER_CALL[kind], "tokens": count * PER_CALL[kind],
             "model": model if kind == "rollout" else optimizer_model} for kind, count in counts.items()]
    total = sum(row["tokens"] for row in rows)
    return {"train": n_train, "val": n_val, "epochs": epochs, "candidates": candidates, "rows": rows,
            "tokens": total, "rollouts": counts["rollout"], "max_tokens": max_tokens, "max_rollouts": max_rollouts,
            "fits": total <= max_tokens and counts["rollout"] <= max_rollouts}


def line(est):
    """The one-line human form."""
    fit = "fits the caps" if est["fits"] else (f"over the caps ({est['max_tokens']:,} tokens, "
                                               f"{est['max_rollouts']} rollouts): the run stops early")
    return (f"~{est['tokens']:,} tokens, {est['rollouts']} rollouts ({est['train']} train + {est['val']} val, "
            f"{est['epochs']} epochs x {est['candidates']} candidates); {fit}")
