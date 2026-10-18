"""The state call's page (hal2 plan 0366): the role detected from the checkout of --repo, one printed line, --no-open,
--role, --text; over test_state's fixture (main checkout `proj`, worktrees 02, 10, 1, farmer-x)."""

import contextlib
import io
import os
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

import state
from test_state import Fixture


class Page(Fixture):
    def run_cli(self, *args: str) -> list[str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(state.main(list(args)), 0)
        return buf.getvalue().splitlines()

    def page_of(self, repo: Path, *args: str) -> Path:
        lines = self.run_cli("--repo", str(repo), "--no-open", *args)
        self.assertEqual(len(lines), 1)
        return Path(lines[0])

    def test_no_open_prints_one_path_under_the_state_dir_and_opens_nothing(self):
        path = self.page_of(self.wt / "02")
        self.assertEqual(path, self.tmp / "xdg/hal2/get-state/proj-02-foreman.html")
        text = path.read_text(encoding="utf-8")
        self.assertIn("<title>proj · foreman 02</title>", text)
        self.assertIn("Plan 0042: the answer", text)
        self.assertIn("<td>two</td>", text)
        self.browser.assert_not_called()

    def test_the_default_opens_the_page_once(self):
        with mock.patch.object(os, "getcwd", return_value=str(self.main)):
            lines = self.run_cli("--repo", str(self.main))
        self.assertEqual(len(lines), 1)
        self.browser.assert_called_once_with(Path(lines[0]).resolve().as_uri())

    def test_the_default_opens_the_servers_url_and_still_writes_the_file(self):
        self.serve.return_value = 47999
        lines = self.run_cli("--repo", str(self.wt / "02"), "--role", "foreman")
        url = f"http://127.0.0.1:47999/?{urlencode({'repo': str(self.wt / '02'), 'role': 'foreman'})}"
        self.assertEqual(lines, [url])
        self.browser.assert_called_once_with(url)
        self.assertTrue((self.tmp / "xdg/hal2/get-state/proj-02-foreman.html").is_file())

    def test_no_open_starts_no_server(self):
        self.page_of(self.wt / "02")
        self.serve.assert_not_called()

    def test_the_role_comes_from_the_checkout(self):
        for repo, name in ((self.main, "proj-main-steward"), (self.wt / "10", "proj-10-foreman"),
                           (self.wt / "farmer-x", "proj-farmer-x-farmer"), (self.wt / "1", "proj-1-unknown")):
            self.assertEqual(self.page_of(repo).stem, name, repo)

    def test_the_main_checkout_of_a_place_is_its_role(self):
        for env, want in (("HAL_VILLAGE", "mayor"), ("HAL_CITY", "lord"), ("HAL_PLANET", "pope")):
            with mock.patch.dict(os.environ, {env: str(self.main)}):
                self.assertEqual(self.page_of(self.main).stem, f"proj-main-{want}")

    def test_role_overrides_the_detection(self):
        for r in ("lord", "pope", "tollman"):
            path = self.page_of(self.wt / "02", "--role", r)
            self.assertEqual(path.stem, f"proj-02-{r}")
            self.assertIn(f"proj · {r} 02", path.read_text(encoding="utf-8"))

    def test_an_unknown_role_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            state.main(["--repo", str(self.main), "--role", "king"])

    def test_the_own_row_is_marked_not_starred(self):
        with mock.patch.object(os, "getcwd", return_value=str(self.wt / "1")):  # an unknown role: today's table
            text = self.page_of(self.wt / "1").read_text(encoding="utf-8")
        self.assertIn('<tr class="marked"><td>1</td>', text)
        self.assertNotIn("**", text)

    def test_the_line_under_the_title(self):
        text = self.page_of(self.main).read_text(encoding="utf-8")
        self.assertRegex(text, r'<p class="meta">main: [0-9a-f]{8} ')

    def test_a_cell_is_escaped(self):
        (self.wt / "10/plans/CURRENT_PLAN").write_text("<script>alert(1)</script>\n")
        text = self.page_of(self.wt / "10").read_text(encoding="utf-8")
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", text)

    def test_text_and_json_write_no_page(self):
        self.run_cli("--repo", str(self.main), "--text")
        self.run_cli("--repo", str(self.main), "--json")
        self.assertFalse((self.tmp / "xdg").exists())
        self.browser.assert_not_called()

    def test_only_the_table_page_reads_the_table_facts(self):
        """Plan 0369 D14: `git status`, `git log` and `git rev-list` per worktree were 60% of a collect's time; only the
        five-cell table shows what they give."""
        self.assertGreater(self.rows()["02"]["uncommitted"], 0)  # its untracked plans/ folder
        light = {r["wt"]: r for r in state.collect(str(self.main), table_facts=False)["rows"]}
        self.assertEqual([light["02"][k] for k in state.TABLE_FACTS], [None, None, None])
        self.assertEqual(light["02"]["plan_number"], "0042")
        facts = lambda repo, role=None: state.page_facts(str(repo), role)  # noqa: E731
        self.assertEqual(facts(self.wt / "farmer-x"), {"table_facts": False, "ledgers": True})
        self.assertEqual(facts(self.wt / "02"), {"table_facts": False, "ledgers": False})  # the foreman's page
        self.assertEqual(facts(self.wt / "1"), {"table_facts": True, "ledgers": False})  # an unknown role: the table
        self.assertEqual(facts(self.wt / "02", "unknown"), {"table_facts": True, "ledgers": False})
        with mock.patch.object(state, "collect", wraps=state.collect) as spy:
            self.page_of(self.wt / "farmer-x")
        self.assertEqual(spy.call_args.kwargs, {"table_facts": False, "ledgers": True})

    def test_the_farmers_collect_reads_the_questions_once_per_plan(self):
        """Plan 0369 D15: the CLI (here a fake reader) once per plan, in the collector's pool; only with `ledgers`."""
        (self.plan_dir / "questions.md").write_text("## Q1 · 2026-10-18 · agent · open\n\n**Q:** Which? a) x, b) y\n")
        seen = []
        with mock.patch.object(state.ledger_sources, "cli_questions", side_effect=lambda path, slug: seen.append(slug)):
            data = state.collect(str(self.main), ledgers=True)  # the CLI "fails": the parser reads the file
        self.assertEqual(seen, ["0042-the-answer"])
        self.assertEqual([(q["wt"], q["n"], q["options"]) for q in data["questions"]], [("02", "Q1", ["x", "y"])])
        self.assertNotIn("questions", state.collect(str(self.main)))

    def test_text_and_json_together_are_refused(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            state.main(["--repo", str(self.main), "--text", "--json"])


if __name__ == "__main__":
    unittest.main()
