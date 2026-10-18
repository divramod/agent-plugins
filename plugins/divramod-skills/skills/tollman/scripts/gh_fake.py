"""A fake `gh` for the watch and triage tests (hal2 plan 0360 step 5): `mtm_scan.run_json` and `mtm_scan.run`
answer from data, every other command (git) runs as it is. No real gh call ever leaves a test."""

from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import gh_runs
import mtm_scan


class FakeGh:
    """`runs`: the landing workflow's runs (`gh run list`), newest first or not; `jobs`: {run id: its jobs};
    `logs`: {run id: its failed log}; `parents`: {commit: [its parents]}. `calls`: every gh command asked."""

    def __init__(self, runs=(), jobs=None, logs=None, parents=None):
        self.runs, self.jobs, self.logs = list(runs), dict(jobs or {}), dict(logs or {})
        self.parents, self.calls = dict(parents or {}), []
        self._run = mtm_scan.run

    def run_json(self, args, cwd=None):
        if args[:1] != ["gh"]:
            return None
        self.calls.append(list(args))
        if args[1:3] == ["run", "list"]:
            return self.runs
        if args[1:3] == ["run", "view"] and args[-2:] == ["--json", "jobs"]:
            return {"jobs": self.jobs.get(str(args[3]), [])}
        if args[1] == "api":
            sha = args[2].rsplit("/", 1)[-1]
            return {"sha": sha, "parents": [{"sha": p} for p in self.parents.get(sha, [])]}
        return None

    def run(self, args, cwd=None):
        if args[:1] != ["gh"]:
            return self._run(args, cwd)
        self.calls.append(list(args))
        return self.logs.get(str(args[3]), "") if args[-1] == "--log-failed" else ""

    def start(self, case):
        """Patch both readers for the test `case` (stopped at its cleanup); no gh_runs round is open."""
        for p in (mock.patch.object(mtm_scan, "run_json", self.run_json), mock.patch.object(mtm_scan, "run", self.run),
                  mock.patch.object(gh_runs, "_round", None)):
            p.start()
            case.addCleanup(p.stop)
        return self


def run(rid, branch, created, status="completed", conclusion="failure", sha=None):
    """One row of `gh run list` (mtm_ci.FIELDS)."""
    return {"databaseId": int(rid), "headBranch": branch, "headSha": sha or str(rid) * 8, "status": status,
            "conclusion": conclusion if status == "completed" else None, "createdAt": created,
            "url": f"https://github.com/x/actions/runs/{rid}"}


def job(name, conclusion="failure", step="test"):
    """One job of `gh run view --json jobs`, with its first failed step."""
    steps = [{"name": "checkout", "conclusion": "success"}, {"name": step, "conclusion": conclusion}]
    return {"name": name, "status": "completed" if conclusion else "in_progress", "conclusion": conclusion,
            "steps": steps}
