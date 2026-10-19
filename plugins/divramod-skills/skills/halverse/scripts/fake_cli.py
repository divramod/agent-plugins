"""A fake hal2-cli-halverse for the tests (plan 0276, D37): a script printing one JSON file per command from a folder.

`terms --json` prints `terms.json`, `terms --json --lang de` `terms-de.json`, `ontology --json` `ontology.json`, `check --json`
`check.json`; a `term` call the file of its words, `term add --from - --dry-run` `term-add-dry.json`, `term short set`
`term-short-set.json` (plan 0276 step 11). A `names <leaf>` call prints `names-<leaf>.json`, or `names-<leaf>-<its first
argument>.json` where that file exists (plan 0283 step 4; hand-written in `fixtures/cli/names/` after the CLI's shapes,
every name invented); a file holding an `error` is printed on stderr with the error's own `exit`. The exit code is the CLI's: 1 for a check whose `ok` is false, 2 for a file
with an `error` or one that is missing, and for a `term` call's error the code's own (3 refused, 4 `changed-meanwhile`
and `locked`, 5 `failed`: the CLI before plan 0318). A file recorded from the CLI since then holds the contract's error
(`exit` in it): it is printed on stderr and the exit is its own. Every call's arguments are appended to the log, and the document of a `--from -` to the
documents' log. `answer` is a program that prints one answer whatever it is asked. The real CLI and the user's files
are never touched.

A fake program runs inside the test's own process (`run_in_process`, patched over `subprocess.run` by `FakeCli` and
`in_process`): a spawned Python costs 30 ms, and the suite calls the fakes some hundred times. test_cli.py's cases keep
the real process (`IN_PROCESS = False`): they are the tests of the boundary itself (arguments, stdin, timeout, exits).
"""
import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
import warnings
from unittest import mock

import cli

HERE = os.path.dirname(os.path.abspath(__file__))
CONTRACT = os.path.join(HERE, "fixtures", "cli", "contract")  # copies of the CLI's expected files
SOURCES = os.path.join(HERE, "fixtures", "cli", "sources")  # the CLI's answers for fixtures/sources
TERM = os.path.join(HERE, "fixtures", "cli", "term")  # the writing calls on the CLI's own fixtures, each going through
NAMES = os.path.join(HERE, "fixtures", "cli", "names")  # the `names` commands' answers, invented names
REFUSED = os.path.join(HERE, "fixtures", "cli", "term-refused")  # the same calls refused
DOCUMENTS = os.path.join(HERE, "fixtures", "cli", "documents")  # the terms' documents the answers were recorded with

SCRIPT = '''#!{python}
import json, os, sys
args = sys.argv[1:]
open({log!r}, "a").write(" ".join(args) + "\\n")
if "--from" in args:
    open({log!r} + ".documents", "a").write(json.dumps(sys.stdin.buffer.read().decode("utf-8")) + "\\n")
name = args[0] + ("-" + args[args.index("--lang") + 1] if "--lang" in args else "")
if name == "term":
    name = "-".join(args[:3 if args[1] == "short" else 2]) + ("-dry" if "--dry-run" in args else "")
if name == "names":
    name = "names-" + args[1]
    if len(args) > 2 and os.path.isfile(os.path.join({folder!r}, name + "-" + args[2] + ".json")):
        name += "-" + args[2]
path = os.path.join({folder!r}, name + ".json")
if not os.path.isfile(path):
    print(json.dumps({{"error": {{"code": "usage", "message": "no fixture " + name, "detail": {{}}}}}}))
    sys.exit(2)
text = open(path, encoding="utf-8").read()
data = json.loads(text)
error = data.get("error") if isinstance(data, dict) else None
if isinstance(error, dict) and "exit" in error:  # the contract's error (plan 0318): stderr alone, the CLI's own exit
    sys.stderr.buffer.write(text.encode("utf-8"))
    sys.stderr.flush()
    sys.exit(error["exit"])
sys.stdout.buffer.write(text.encode("utf-8"))
sys.stdout.flush()
refused = {{"usage": 2, "unreadable": 2, "changed-meanwhile": 4, "locked": 4, "failed": 5}}
if "error" in data:
    sys.exit(refused.get(data["error"].get("code"), 3) if args[0] == "term" else 2)
sys.exit(1 if data.get("ok") is False else 0)
'''

ANSWER = '''#!{python}
import json, sys
args = sys.argv[1:]
open({log!r}, "a").write(" ".join(args) + "\\n")
if "--from" in args:
    open({log!r} + ".documents", "a").write(json.dumps(sys.stdin.buffer.read().decode("utf-8")) + "\\n")
print({body!r})
sys.exit({code})
'''


REAL_RUN = subprocess.run
SHEBANG = ("#!%s\n" % sys.executable).encode()


def _fake_program(argv) -> str:
    """The source of `argv[0]` when it is one of these fakes (a file starting with this Python's shebang), else ''."""
    path = argv[0] if isinstance(argv, (list, tuple)) and argv and isinstance(argv[0], str) else ""
    if not os.path.isabs(path) or not os.path.isfile(path) or not os.access(path, os.X_OK):
        return ""
    with open(path, "rb") as handle:
        data = handle.read()
    return data.decode("utf-8") if data.startswith(SHEBANG) else ""


def run_in_process(argv, *args, **kw):
    """`subprocess.run` for a fake program: its source executed here with its argv, stdin and captured output, its
    `sys.exit` the exit code; any other command runs for real."""
    source = _fake_program(argv)
    if not source or args or kw.get("shell"):
        return REAL_RUN(argv, *args, **kw)
    feed = kw.get("input")
    feed = feed.encode("utf-8") if isinstance(feed, str) else (feed or b"")
    out, err = io.BytesIO(), io.BytesIO()
    streams = [io.TextIOWrapper(io.BytesIO(feed), encoding="utf-8"),
               io.TextIOWrapper(out, encoding="utf-8", write_through=True),
               io.TextIOWrapper(err, encoding="utf-8", write_through=True)]
    saved = sys.argv, sys.stdin, sys.stdout, sys.stderr
    sys.argv, (sys.stdin, sys.stdout, sys.stderr) = list(argv), streams
    code = 0
    try:
        with warnings.catch_warnings():  # a real process ends with its files closed: no warning reaches its stderr
            warnings.simplefilter("ignore", ResourceWarning)
            exec(compile(source, argv[0], "exec"), {"__name__": "__main__"})
    except SystemExit as stop:
        code = stop.code if isinstance(stop.code, int) else (0 if stop.code is None else 1)
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        sys.argv, sys.stdin, sys.stdout, sys.stderr = saved
    stdout, stderr = out.getvalue(), err.getvalue()
    if kw.get("text") or kw.get("encoding") or kw.get("universal_newlines"):
        stdout, stderr = stdout.decode(kw.get("encoding") or "utf-8"), stderr.decode(kw.get("encoding") or "utf-8")
    return subprocess.CompletedProcess(argv, code, stdout, stderr)


def in_process(case: unittest.TestCase):
    """Runs every fake program of `case` in its process, until the case ends."""
    patch = mock.patch.object(subprocess, "run", run_in_process)
    patch.start()
    case.addCleanup(patch.stop)


def program(path: str, log: str, payload, code: int = 0):
    """A program at `path` that logs its arguments and prints `payload` (JSON, or a text as it is) with the exit code."""
    body = payload if isinstance(payload, str) else json.dumps(payload)
    with open(path, "w") as handle:
        handle.write(ANSWER.format(python=sys.executable, log=log, body=body, code=code))
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


def fixture(folder: str, name: str):
    with open(os.path.join(folder, name + ".json"), encoding="utf-8") as handle:
        return json.load(handle)


class FakeCli(unittest.TestCase):
    """A test case with `self.use(folder)`: the CLI of the test is a script printing that folder's files."""

    IN_PROCESS = True

    def setUp(self):
        if self.IN_PROCESS:
            in_process(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "hal2-cli-halverse")
        self.log = os.path.join(self.tmp.name, "args.txt")
        self.saved = os.environ.get(cli.CLI_ENV)
        os.environ[cli.CLI_ENV] = self.path
        self.use(SOURCES)

    def tearDown(self):
        if self.saved is None:
            os.environ.pop(cli.CLI_ENV, None)
        else:
            os.environ[cli.CLI_ENV] = self.saved
        self.tmp.cleanup()

    def script(self, body: str):
        with open(self.path, "w") as handle:
            handle.write(body)
        os.chmod(self.path, os.stat(self.path).st_mode | stat.S_IXUSR)

    def use(self, folder: str):
        self.script(SCRIPT.format(python=sys.executable, log=self.log, folder=folder))

    def answer(self, payload, code: int = 0):
        """The CLI of the test prints `payload` and exits with `code`, whatever it is asked."""
        program(self.path, self.log, payload, code)

    def args(self):
        if not os.path.isfile(self.log):
            return []
        with open(self.log) as handle:
            return handle.read().splitlines()

    def documents(self):
        """The document of every `--from -` call, in the calls' order."""
        if not os.path.isfile(self.log + ".documents"):
            return []
        with open(self.log + ".documents") as handle:
            return [json.loads(line) for line in handle.read().splitlines()]


class InFolder(FakeCli):
    """A FakeCli whose test runs inside its scratch folder: no repository lies around it, and a relative path of an
    answer names no file of the user's. `main` runs `halverse.py`'s command line."""

    def setUp(self):
        super().setUp()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.cwd)
        super().tearDown()

    def main(self, *argv):
        """(the exit code, stdout, stderr) of `halverse.py <argv>`."""
        import halverse
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = halverse.main(list(argv))
        return code, out.getvalue(), err.getvalue()
