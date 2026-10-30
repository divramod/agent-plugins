"""A fake `gh` for the watch and triage tests (hal2 plan 0360 step 5): `mtm_scan.run_json` and `mtm_scan.run`
answer from data, every other command (git) runs as it is. No real gh call ever leaves a test."""

from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import gh_runs
import mtm_ci
import mtm_scan
import pass_timing


class FakeGh:
    """`runs`: the landing workflow's runs as `gh run list` rows (mtm_ci.FIELDS; a row's `path` its workflow file,
    else the first landing workflow), newest first or not, which `gh api .../actions/runs?...` (mtm_ci.RUNS_ARGS, the
    one runs read of a round) answers in the API's shape and `gh run list` as they are; `jobs`: {run id: its jobs};
    `logs`: {run id: its failed log}; `parents`: {commit: [its parents]}; `runners`: the rows of `gh api
    .../actions/runners` (None: GitHub does not answer); `api_jobs`: {run id: its jobs as `gh api .../runs/<id>/jobs`
    lists them (id, name, status, labels, created_at)}. `calls`: every gh command asked."""

    def __init__(self, runs=(), jobs=None, logs=None, parents=None, runners=None, api_jobs=None):
        self.runs, self.jobs, self.logs = list(runs), dict(jobs or {}), dict(logs or {})
        self.runners, self.api_jobs = runners, dict(api_jobs or {})
        self.parents, self.calls = dict(parents or {}), []
        self._run = mtm_scan.run

    def run_json(self, args, cwd=None):
        if args[:1] != ["gh"]:
            return None
        self.calls.append(list(args))
        pass_timing.count_gh(args)
        if args[1:3] == ["run", "list"]:
            return self.runs
        if args[1:3] == ["run", "view"] and args[-2:] == ["--json", "jobs"]:
            return {"jobs": self.jobs.get(str(args[3]), [])}
        if args[1] == "api" and "/actions/runners" in args[2]:
            return None if self.runners is None else {"runners": self.runners}
        if args[1] == "api" and args[2].split("?")[0].endswith("/actions/runs"):
            return [api_run(r) for r in self.runs]
        if args[1] == "api" and "/actions/runs/" in args[2]:
            return {"jobs": self.api_jobs.get(args[2].split("/actions/runs/")[1].split("/")[0], [])}
        if args[1] == "api":
            sha = args[2].rsplit("/", 1)[-1]
            return {"sha": sha, "parents": [{"sha": p} for p in self.parents.get(sha, [])]}
        return None

    def runs_lists(self) -> int:
        """How many runs lists (`gh api .../actions/runs?...`) were asked."""
        return sum(1 for c in self.calls if c[1:2] == ["api"] and c[2].split("?")[0].endswith("/actions/runs"))

    def runner_lists(self) -> int:
        """How many runners lists (`gh api .../actions/runners`) were asked."""
        return sum(1 for c in self.calls if c[1:2] == ["api"] and "/actions/runners" in c[2])

    def run(self, args, cwd=None):
        if args[:2] == ["git", "ls-tree"]:  # the default branch has every landing workflow file (mtm_ci.live_land_names)
            return "".join(f".github/workflows/{n}\n" for n in mtm_ci.LAND_NAMES)
        if args[:1] != ["gh"]:
            return self._run(args, cwd)
        self.calls.append(list(args))
        pass_timing.count_gh(args)
        return self.logs.get(str(args[3]), "") if args[-1] == "--log-failed" else ""

    def start(self, case):
        """Patch both readers for the test `case` (stopped at its cleanup); no gh_runs round is open."""
        for p in (mock.patch.object(mtm_scan, "run_json", self.run_json), mock.patch.object(mtm_scan, "run", self.run),
                  mock.patch.object(mtm_ci, "_git", self.run),
                  mock.patch.object(gh_runs, "_round", None)):
            p.start()
            case.addCleanup(p.stop)
        return self


def run(rid, branch, created, status="completed", conclusion="failure", sha=None):
    """One row of `gh run list` (mtm_ci.FIELDS)."""
    return {"databaseId": int(rid), "headBranch": branch, "headSha": sha or str(rid) * 8, "status": status,
            "conclusion": conclusion if status == "completed" else None, "createdAt": created,
            "url": f"https://github.com/x/actions/runs/{rid}"}


def api_run(row: dict) -> dict:
    """A `run` row as GitHub's runs list gives it (mtm_ci.RUNS_ARGS' jq projection): the inverse of mtm_ci.as_row."""
    out = {theirs: row.get(ours) for theirs, ours in mtm_ci.AS_ROW.items()}
    out["path"] = row.get("path") or f".github/workflows/{mtm_ci.LAND_NAMES[0]}"
    return out


def job(name, conclusion="failure", step="test"):
    """One job of `gh run view --json jobs`, with its first failed step."""
    steps = [{"name": "checkout", "conclusion": "success"}, {"name": step, "conclusion": conclusion}]
    return {"name": name, "status": "completed" if conclusion else "in_progress", "conclusion": conclusion,
            "steps": steps}


def runner(name, status="online", labels=(), busy=False):
    """One row of `gh api .../actions/runners`."""
    return {"name": name, "status": status, "busy": busy, "labels": [{"name": x} for x in labels]}


def api_job(jid, name, labels, created, status="queued"):
    """One job of `gh api .../actions/runs/<id>/jobs`."""
    return {"id": jid, "name": name, "status": status, "labels": list(labels), "created_at": created}
