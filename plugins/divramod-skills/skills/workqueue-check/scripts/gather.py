"""Run the CLIs the check reads; each returns (data, message): data None with a message when it cannot be had."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "scripts"))
import skillpath  # noqa: E402

CLI = "hal2-cli-workqueue"


def _json(argv, timeout=60):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as err:
        return None, 3, f"{argv[0]}: {err}"
    try:
        return json.loads(done.stdout), done.returncode, ""
    except ValueError:
        return None, done.returncode, (done.stderr or done.stdout).strip()[:300] or f"{argv[0]}: no JSON"


def cli():
    return os.environ.get("HAL2_WORKQUEUE_BIN") or shutil.which(CLI)


def workqueue(sub, since, extra=()):
    exe = cli()
    if not exe:
        return None, f"{CLI} is not installed yet (cargo install --path code/rust/apps/{CLI})"
    data, code, message = _json([exe, sub, "--since", since, "--json", *extra])
    if data is None:
        return None, message or f"{CLI} {sub} failed ({code})"
    return data.get("data", data) if isinstance(data, dict) else data, ""


def bench_main():
    explicit = os.environ.get("HAL2_WORKQUEUE_BENCH")
    if explicit:
        return Path(explicit)
    root = skillpath.repo_root(__file__)
    for base in (root, Path.home() / "a" / "hal2"):
        if base and (base / "code/python/scripts/workqueue-bench/main.py").is_file():
            return base / "code/python/scripts/workqueue-bench/main.py"
    return None


def bench_compare():
    """(result, message, exit code): exit 1 = slower, 3 = no baseline or no results."""
    main = bench_main()
    if not main:
        return None, "the workqueue-bench unit is not in this checkout", 3
    data, code, message = _json([sys.executable, str(main), "compare", "--json"])
    if data is None:
        return None, message or "no baseline yet (take one on a quiet Mac after the user's go)", code
    return data, "", code
