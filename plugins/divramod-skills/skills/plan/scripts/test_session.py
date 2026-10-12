"""session.py: the live session's model, effort and window, each with its source."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import session  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "session.py"
CLEAN_ENV = {"CLAUDE_CONTEXT_WINDOW": "", "CLAUDE_CODE_DISABLE_1M_CONTEXT": "", "CLAUDE_EFFORT": "",
             "ANTHROPIC_MODEL": "", "CLAUDE_PID": ""}


def assistant(sidechain=False, **fields) -> str:
    return json.dumps({"type": "assistant", "isSidechain": sidechain, **fields,
                       "message": {"usage": {"input_tokens": 10, "cache_read_input_tokens": 90}}})


def command(text: str, as_blocks=False) -> str:
    content = f"<local-command-stdout>{text}</local-command-stdout>"
    if as_blocks:
        content = [{"type": "text", "text": content}]
    return json.dumps({"type": "user", "message": {"role": "user", "content": content}})


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home / ".claude").mkdir()
        env = mock.patch.dict(os.environ, CLEAN_ENV)
        env.start()
        self.addCleanup(env.stop)
        self.process = mock.patch.object(session, "claude_args", return_value=None)
        self.args = self.process.start()
        self.addCleanup(self.process.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def transcript(self, *lines) -> Path:
        path = self.home / "t.jsonl"
        path.write_text("\n".join(lines) + "\n")
        return path

    def settings(self, **values) -> None:
        (self.home / ".claude" / "settings.json").write_text(json.dumps(values))

    def live(self, *lines) -> dict:
        return session.values(session.scan(self.transcript(*lines)) if lines else None, self.home)

    def test_the_transcripts_main_chain_comes_first(self):
        result = self.live(assistant(requestedModel="claude-opus-5-5[1m]", effort="max"),
                           assistant(sidechain=True, requestedModel="claude-sonnet-5-5", effort="low"), "not json")
        self.assertEqual((result["model"], result["effort"], result["window"]), ("claude-opus-5-5[1m]", "max", "1m"))
        self.assertEqual(result["sources"], {"model": "requestedModel in the transcript",
                                             "effort": "effort in the transcript",
                                             "window": "1M in the model's name"})
        self.assertEqual(result["used"], 100)

    def test_a_later_switch_wins_over_the_last_assistant_entry_and_the_other_way_round(self):
        result = self.live(assistant(requestedModel="claude-opus-5-5", effort="medium"),
                           command("Set model to `Sonnet 5.5` and saved as your default for new sessions"),
                           command("Set effort level to max (this session only): Maximum capability"))
        self.assertEqual((result["model"], result["effort"]), ("Sonnet 5.5", "max"))
        self.assertEqual(result["sources"]["model"], "/model in the transcript")
        self.assertEqual(result["sources"]["effort"], "/effort in the transcript")
        result = self.live(command("Set effort level to max (this session only)", as_blocks=True),
                           assistant(requestedModel="claude-opus-5-5", effort="high"))
        self.assertEqual((result["model"], result["effort"]), ("claude-opus-5-5", "high"))
        result = self.live(command("Set effort level to xhigh (saved as your default)", as_blocks=True))
        self.assertEqual(result["effort"], "xhigh")

    def test_model_falls_back_to_the_process_then_the_environment_then_settings(self):
        self.settings(model="opus")
        self.args.return_value = ["claude", "--model", "opus[1m]", "--effort", "xhigh", "--", "--model x"]
        result = self.live()
        self.assertEqual((result["model"], result["effort"]), ("opus[1m]", "xhigh"))
        self.assertEqual(result["sources"]["model"], "the session process's --model")
        self.assertEqual(result["sources"]["effort"], "the session process's --effort")
        self.args.return_value = ["/usr/local/bin/claude", "--continue", "--", "--model", "haiku"]
        with mock.patch.dict(os.environ, {"ANTHROPIC_MODEL": "claude-sonnet-5-5"}):
            result = self.live()
        self.assertEqual((result["model"], result["sources"]["model"]), ("claude-sonnet-5-5", "$ANTHROPIC_MODEL"))
        result = self.live()
        self.assertEqual((result["model"], result["sources"]["model"]),
                         ("opus", str(self.home / ".claude" / "settings.json")))
        (self.home / ".claude" / "settings.json").unlink()
        result = self.live()
        self.assertEqual((result["model"], result["effort"], result["window"]), ("", "", "200k"))
        self.assertEqual(result["sources"], {"model": "default", "effort": "default", "window": "default"})

    def test_effort_falls_back_to_the_environment_the_process_then_settings(self):
        self.args.return_value = ["claude", "--effort=low"]
        with mock.patch.dict(os.environ, {"CLAUDE_EFFORT": "high"}):
            self.assertEqual(self.live()["sources"]["effort"], "$CLAUDE_EFFORT")
        self.assertEqual(self.live()["effort"], "low")
        self.args.return_value = None
        self.settings(model="claude-opus-5-5", effortLevel="medium",
                      modelSettings={"claude-opus-5-5": {"effortLevel": "high"},
                                     "claude-sonnet-5-5": {"effortLevel": "low"}})
        self.assertEqual(self.live()["effort"], "high")
        # The model's settings key from an alias or a display name; else the global effortLevel.
        self.assertEqual(self.live(command("Set model to `Sonnet 5.5 (1M context)`"))["effort"], "low")
        self.assertEqual(self.live(assistant(requestedModel="sonnet"))["effort"], "low")
        self.assertEqual(self.live(assistant(requestedModel="haiku"))["effort"], "medium")

    def test_window(self):
        cases = {"opus": 1_000_000, "sonnet[1m]": 1_000_000, "claude-opus-5-5": 1_000_000,
                 "claude-sonnet-5-5": 1_000_000, "claude-haiku-5-5": 1_000_000, "Opus 5.5 (1M context)": 1_000_000,
                 "Sonnet 5.5": 1_000_000, "claude-opus-4-6": 200_000, "claude-opus-4-6[1m]": 1_000_000,
                 "Opus 4.6": 200_000, "": 200_000}
        for model, window in cases.items():
            self.assertEqual(session.window_of(model)[0], window, model)
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_DISABLE_1M_CONTEXT": "1"}):
            self.assertEqual(session.window_of("opus[1m]"), (200_000, "$CLAUDE_CODE_DISABLE_1M_CONTEXT"))
            # More in use than 200k: it must be the 1M window after all.
            self.assertEqual(session.window_of("opus", used=250_000)[0], 1_000_000)
        with mock.patch.dict(os.environ, {"CLAUDE_CONTEXT_WINDOW": "500000"}):
            self.assertEqual(session.window_of("opus[1m]"), (500_000, "$CLAUDE_CONTEXT_WINDOW"))
        self.assertEqual([session.label(n) for n in (200_000, 1_000_000, 500_000, 123_456)],
                         ["200k", "1m", "500k", "123456"])

    def test_family_and_model_id(self):
        for model in ("opus", "opus[1m]", "claude-opus-5-5", "claude-opus-5-5[1m]", "Opus 5.5 (1M context)"):
            self.assertEqual(session.family(model), "opus", model)
        self.assertEqual(session.family("some-model"), "some-model")
        self.assertEqual(session.model_id("Opus 5.5 (1M context)"), "claude-opus-5-5")
        self.assertEqual(session.model_id("claude-sonnet-5-5[1m]"), "claude-sonnet-5-5")

    def test_flag_stops_at_the_end_of_the_options(self):
        self.assertEqual(session.flag(["claude", "--model", "opus", "--", "--effort", "max"], "--effort"), "")
        self.assertEqual(session.flag(["claude", "--effort=max"], "--effort"), "max")
        self.assertEqual(session.flag(None, "--model"), "")


class SessionCliTest(unittest.TestCase):
    """The CLI, with a fake `ps` so the real session running these tests never counts."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.projects = self.home / ".claude" / "projects" / "-some-repo"
        self.projects.mkdir(parents=True)
        (self.home / "bin").mkdir()
        self.fake_ps()

    def tearDown(self):
        self.tmp.cleanup()

    def fake_ps(self, *rows: str) -> None:
        lines = "".join(f"echo '{row}'\n" for row in rows)
        (self.home / "bin" / "ps").write_text(f"#!/bin/sh\necho \"$PPID 900 python3 session.py\"\n{lines}")
        (self.home / "bin" / "ps").chmod(0o755)

    def run_session(self, *args, env=None) -> dict:
        full_env = {"HOME": str(self.home), "PATH": f"{self.home / 'bin'}:{os.environ.get('PATH', '')}"}
        full_env.update(env or {})
        out = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=full_env,
                             check=True)
        return json.loads(out.stdout)

    def test_prints_the_values_of_the_sessions_transcript(self):
        (self.projects / "s1.jsonl").write_text(assistant(requestedModel="claude-sonnet-5-5", effort="high") + "\n")
        result = self.run_session(env={"CLAUDE_CODE_SESSION_ID": "s1"})
        self.assertEqual({k: result[k] for k in ("model", "effort", "window", "window_tokens", "used")},
                         {"model": "claude-sonnet-5-5", "effort": "high", "window": "1m",
                          "window_tokens": 1_000_000, "used": 100})
        self.assertEqual(result["transcript"], str(self.projects / "s1.jsonl"))
        self.assertEqual(self.run_session("--transcript", str(self.projects / "s1.jsonl"))["effort"], "high")

    def test_the_claude_process_ancestor_or_claude_pid(self):
        self.fake_ps("900 800 /bin/zsh -c python3 session.py",
                     "800 1 claude --remote-control x --model claude-opus-5-5 --effort max -- prompt --effort low")
        result = self.run_session()
        self.assertIsNone(result["transcript"])
        self.assertEqual((result["model"], result["effort"], result["window"]), ("claude-opus-5-5", "max", "1m"))
        # No claude above this script (e.g. a hal2 job's shell): $CLAUDE_PID names the session's process.
        self.fake_ps("900 1 /bin/zsh", "4242 1 claude --model sonnet --effort medium")
        self.assertEqual(self.run_session()["model"], "")
        result = self.run_session(env={"CLAUDE_PID": "4242"})
        self.assertEqual((result["model"], result["effort"]), ("sonnet", "medium"))


if __name__ == "__main__":
    unittest.main()
