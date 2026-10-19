"""The optimize loop (plan 0390 step 4; research 0100 Next steps, SkillOpt's loop). Stdlib only.

    baseline: the incumbent (the skill's SKILL.md, candidate c0) on train, then val
    per epoch n (at most `epochs`):
      train at 100%             -> stop `train_perfect` (nothing to reflect on)
      val at 100%               -> stop `val_perfect` (no candidate can pass the strict-gain gate)
      reflect on the incumbent's failed TRAIN rollouts (never a val task), one call
      up to `candidates` edit sets (each told the ones before), applied by edits.py, scored on train then val
      gate (strict gain on val against the epoch's incumbent): the best accepted one becomes the incumbent; every
      other scored one goes into rejected.jsonl, a rejected one with its margin to the incumbent, an accepted one
      that lost with its margin to the winner (reason `lost to <winner>`)
      two epochs in a row without a winner -> stop `two_rejected`
    `epochs` done -> stop `epochs`; a cap (budget.BudgetExceeded, before any call) -> stop `budget`, and a candidate
      the gate accepted earlier in that epoch is still promoted (a cap never loses a validated winner)

Every rollout is checked against the ledger first (the largest call so far, at the start estimate.ROLLOUT) and
charged its exact usage after (a rollout cut off before its result event at least that estimate, budget.floored).
The run reads the skill's folder only: rollouts copy it into one workspace per run, the optimizer calls run in its
sibling `<workspace>-llm`; both are removed at the end, with the `~/.claude/projects/` folders the run made for them
(projects.py); neither the workspace nor the run folder may lie inside the skill's folder. `best.diff` and the report are
written at the end (the report also while the run goes, runs.py's folder layout).
"""

import json
import shutil
import tempfile
from pathlib import Path

import budget
import edits
import estimate
import evalset
import gate
import judge
import projects
import reflect
import rollout
import runs

DEFAULTS = {"epochs": 3, "candidates": 2, "max_tokens": budget.DEFAULT_MAX_TOKENS,
            "max_rollouts": budget.DEFAULT_MAX_ROLLOUTS, "model": "haiku", "optimizer_model": "sonnet",
            "max_turns": rollout.DEFAULT_TURNS, "timeout": rollout.DEFAULT_TIMEOUT}
PERFECT = 1 - gate.EPSILON


class RunError(Exception):
    """The run cannot start (no SKILL.md, a bad or skeleton eval set, a folder inside the skill)."""


def _means(scores):
    return {split: round(scores[split]["mean"], 6) for split in ("train", "val") if split in scores}


class Run:
    """One optimize run of the skill at `skill_dir` into `run_dir` (module doc)."""

    def __init__(self, skill_dir, run_dir, settings=None, *, workspace=None, support=None, claude=None, env=None):
        self.skill_dir, self.run_dir = Path(skill_dir).resolve(), Path(run_dir)
        self.settings = dict(DEFAULTS, **{k: v for k, v in (settings or {}).items() if v is not None})
        self.name = runs.skill_name(self.skill_dir)
        self.workspace = Path(workspace or Path(tempfile.gettempdir()) / "optimize-skill" /
                              f"ws-{self.name}-{self.run_dir.name}")
        self.llm_cwd = self.workspace.with_name(self.workspace.name + "-llm")
        for folder in (self.run_dir, self.workspace, self.llm_cwd):
            if runs.inside(folder, self.skill_dir):
                raise RunError(f"{folder} lies inside the skill's folder, which a run never writes")
        if self.llm_cwd.exists() and any(self.llm_cwd.iterdir()):
            raise RunError(f"{self.llm_cwd} is not empty: the run removes it at the end")
        md = self.skill_dir / "SKILL.md"
        if not md.is_file():
            raise RunError(f"no SKILL.md in {self.skill_dir}")
        self.original = md.read_text(encoding="utf-8")
        self.evals = self._evals()
        self.support, self.claude, self.env = support, claude, env
        try:
            self.ledger = budget.Ledger(self.run_dir / "ledger.jsonl", self.settings["max_tokens"],
                                        self.settings["max_rollouts"])
        except ValueError as exc:
            raise RunError(f"caps: {exc}") from None
        self.rejected = reflect.RejectedBuffer(self.run_dir / "rejected.jsonl")
        self.largest, self.pending = 0, None
        self.report = {"schema": 1, "state": "running", "skill": self.name, "skill_dir": str(self.skill_dir),
                       "run_id": self.run_dir.name, "run_dir": str(self.run_dir), "started": runs.now(),
                       "settings": self.settings, "baseline": None, "best": None, "epochs": [], "stop": None}

    def _evals(self):
        try:
            data = evalset.load(self.skill_dir)
        except evalset.EvalSetError as exc:
            raise RunError(f"eval set: {exc}") from None
        if evalset.is_skeleton({"evals": data.evals}):
            raise RunError("the eval set is still the skeleton: draft its prompts and checks first")
        return data

    def _save(self, cid, name, obj):
        folder = self.run_dir / "candidates" / cid
        folder.mkdir(parents=True, exist_ok=True)
        if isinstance(obj, str):
            (folder / name).write_text(obj, encoding="utf-8")
        else:
            runs.write_json(folder / name, obj)

    def _rollout(self, cid, skill_md, case, split):
        self.ledger.check(self.largest or estimate.ROLLOUT, "rollout")
        result = rollout.run(self.name, skill_md, case, skill_dir=self.skill_dir, workspace=self.workspace,
                             support=self.support, model=self.settings["model"],
                             max_turns=self.settings["max_turns"], timeout=self.settings["timeout"],
                             claude=self.claude, env=self.env)
        usage, extra = result["usage"], {}
        if result.get("truncated"):  # its stream under-counts it: at least the estimate it was checked against
            usage, extra = budget.floored(usage, self.largest or estimate.ROLLOUT), {"floored": True}
        self.ledger.charge(usage, kind="rollout", cost_usd=result["cost_usd"], eval_id=result["eval_id"],
                           candidate=cid, split=split, error=result["error"], **extra)
        if not result.get("truncated"):  # the floor is the largest complete call
            self.largest = max(self.largest, budget.tokens(result["usage"]))
        with (self.run_dir / "candidates" / cid / "rollouts.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(dict(result, split=split), ensure_ascii=False) + "\n")
        return result

    def score(self, cid, skill_md):
        """{"train": judge_split + results, "val": ...}: every eval of train, then of val."""
        self._save(cid, "SKILL.md", skill_md)
        scores = {}
        for split, cases in (("train", self.evals.train()), ("val", self.evals.val())):
            results = {str(case["id"]): self._rollout(cid, skill_md, case, split) for case in cases}
            scores[split] = dict(judge.judge_split(cases, results), results=results)
        self._save(cid, "scores.json", {split: {"mean": s["mean"], "evals": s["evals"]} for split, s in scores.items()})
        return scores

    def failures(self, scores):
        """The incumbent's failed TRAIN rollouts as reflect.py's failure dicts."""
        train = scores["train"]
        out = [{"eval": self.evals.get(j["eval_id"]), "result": train["results"].get(j["eval_id"]), "judged": j}
               for j in train["evals"]]
        return [failure for failure in out if reflect.is_failed(failure)]

    def candidate(self, epoch, k, incumbent, reflection, proposed):
        """Propose, apply, score and gate one candidate; its report entry (+ `scores`, `text` when scored)."""
        cid = f"e{epoch}c{k}"
        out = reflect.propose(incumbent["text"], reflection, ledger=self.ledger, rejected=self.rejected.recent(),
                              proposed=proposed, model=self.settings["optimizer_model"], claude=self.claude,
                              env=self.env, cwd=self.llm_cwd, epoch=epoch, candidate=cid)
        entry = {"id": cid, "error": out["error"], "edits": out["edits"], "accepted": False}
        if out["edits"] is None:
            return entry
        proposed.append(out["edits"])
        applied = edits.apply(incumbent["text"], out["edits"])
        self._save(cid, "edits.json", {"edits": out["edits"], "verdicts": applied["verdicts"]})
        entry["applied"] = applied["applied"]
        if not applied["changed"]:
            entry["error"] = "no edit applied"
            self.rejected.add(out["edits"], None, epoch=epoch, candidate=cid, reason="no edit applied")
            return entry
        scores = self.score(cid, applied["text"])
        verdict = gate.decide(scores["val"], incumbent["scores"]["val"])
        entry.update(_means(scores), margin=round(verdict["margin"], 6), gate=verdict["reason"],
                     accepted=verdict["accept"], scores=scores, text=applied["text"])
        if not verdict["accept"]:
            self.rejected.add(out["edits"], verdict["margin"], epoch=epoch, candidate=cid, **_means(scores))
        return entry

    def epoch(self, n, incumbent):
        """One epoch; the new incumbent, or None when no candidate passed the gate."""
        record = {"epoch": n, "incumbent": incumbent["id"], "reflection_error": None, "candidates": [],
                  "winner": None}
        self.report["epochs"].append(record)
        self.pending = (record, [])
        reflected = reflect.reflect(incumbent["text"], self.failures(incumbent["scores"]), ledger=self.ledger,
                                    model=self.settings["optimizer_model"], claude=self.claude, env=self.env,
                                    cwd=self.llm_cwd, epoch=n)
        (self.run_dir / "reflections").mkdir(parents=True, exist_ok=True)
        (self.run_dir / "reflections" / f"{n}.md").write_text(reflected["text"], encoding="utf-8")
        if reflected["error"]:
            record["reflection_error"] = reflected["error"]
            return self.promote()
        proposed = []
        for k in range(1, self.settings["candidates"] + 1):
            entry = self.candidate(n, k, incumbent, reflected["text"], proposed)
            record["candidates"].append({key: v for key, v in entry.items() if key not in ("scores", "text")})
            if entry["accepted"]:
                self.pending[1].append(entry)
        return self.promote()

    def promote(self):
        """The running epoch's best accepted candidate as the new incumbent, or None; the other accepted ones go
        into rejected.jsonl with their margin to it. Called at the epoch's end and on a cap stop inside it."""
        record, accepted = self.pending or (None, [])
        self.pending = None
        if not accepted:
            return None
        best = max(accepted, key=lambda e: (e["val"], e["train"]))
        record["winner"] = best["id"]
        for entry in accepted:
            if entry is not best:
                self.rejected.add(entry["edits"], round(entry["val"] - best["val"], 6), epoch=record["epoch"],
                                  candidate=entry["id"], reason=f"lost to {best['id']}", gate_margin=entry["margin"],
                                  **_means(entry["scores"]))
        return {"id": best["id"], "text": best["text"], "scores": best["scores"]}

    def loop(self):
        """(incumbent, stop reason, detail); the incumbent is the best validated candidate so far."""
        incumbent = {"id": "c0", "text": self.original, "scores": None}
        try:
            incumbent["scores"] = self.score("c0", self.original)
            self.report["baseline"] = _means(incumbent["scores"])
            self._write(incumbent)
            misses = 0
            for n in range(1, self.settings["epochs"] + 1):
                if incumbent["scores"]["train"]["mean"] >= PERFECT:
                    return incumbent, "train_perfect", f"train at 100% before epoch {n}"
                if incumbent["scores"]["val"]["mean"] >= PERFECT:  # the strict-gain gate cannot pass
                    return incumbent, "val_perfect", f"val at 100% before epoch {n}: no candidate can beat it"
                winner = self.epoch(n, incumbent)
                incumbent, misses = (winner, 0) if winner else (incumbent, misses + 1)
                self._write(incumbent)
                if misses >= 2:
                    return incumbent, "two_rejected", f"epochs {n - 1} and {n} found no better candidate"
            return incumbent, "epochs", f"{self.settings['epochs']} epochs done"
        except budget.BudgetExceeded as exc:
            winner = self.promote()  # a candidate the gate accepted before the cap stays the result
            return winner or incumbent, "budget", str(exc)

    def _write(self, incumbent=None):
        if incumbent is not None and incumbent.get("scores"):
            self.report["best"] = dict(_means(incumbent["scores"]), candidate=incumbent["id"])
        self.report["tokens"] = self.ledger.summary()
        runs.write_json(self.run_dir / runs.REPORT, self.report)

    def run(self):
        """Run the loop to its stop, write best.diff and the final report; returns the report."""
        self._write()
        made = projects.missing([self.workspace, self.llm_cwd], self.env)
        self.llm_cwd.mkdir(parents=True, exist_ok=True)
        try:
            incumbent, reason, detail = self.loop()
        finally:
            for folder in (self.workspace, self.llm_cwd):
                shutil.rmtree(folder, ignore_errors=True)
            self.report["removed"] = projects.remove(made)
        path, root = runs.diff_target(self.skill_dir)
        improved = incumbent["id"] != "c0"
        diff = edits.unified_diff(self.original, incumbent["text"], path) if improved else ""
        (self.run_dir / runs.DIFF).write_text(diff, encoding="utf-8")
        self.report.update(state="done", finished=runs.now(), improved=improved, stop={"reason": reason,
                           "detail": detail}, diff=str(self.run_dir / runs.DIFF), apply_in=str(root),
                           apply=f"git -C {root} apply {self.run_dir / runs.DIFF}" if improved else None)
        self._write(incumbent if incumbent.get("scores") else None)
        return self.report
