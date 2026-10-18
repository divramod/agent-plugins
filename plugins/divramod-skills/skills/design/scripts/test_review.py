"""The review state (hal2 plan 0364, D7): atomic state.json, accept rules, comments, status and accepted views."""
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import review  # noqa: E402
import store  # noqa: E402

NOW = dt.datetime(2026, 10, 18, 12, 0, tzinfo=dt.timezone.utc)


def make_folder(root: Path) -> Path:
    folder = root / "plans" / "0070-login"
    folder.mkdir(parents=True)
    (folder / "spec.md").write_text("# Spec 0070: login\n")
    for _ in range(2):
        path = store.new_version(folder, "login", "gui", title="login page", now=NOW)
        (path / "screen.html").write_text("<p>hi</p>")
    store.new_version(folder, "login", "flow", now=NOW)
    return folder


class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = make_folder(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def state(self):
        return json.loads(review.state_path(self.folder).read_text())

    def test_an_id_with_a_trailing_newline_is_refused(self):
        for design in ("login/gui/v1\n", "login/gui/v1\n\n", "\nlogin/gui/v1"):
            with self.assertRaises(review.ReviewError, msg=repr(design)):
                review.check_id(self.folder, design)
            with self.assertRaises(review.ReviewError, msg=repr(design)):
                review.set_accepted(self.folder, design, True)
        self.assertFalse(review.state_path(self.folder).exists())

    def test_missing_state_is_empty_and_write_is_atomic(self):
        self.assertEqual(review.load(self.folder), {"schema": 1, "designs": {}})
        review.set_accepted(self.folder, "login/gui/v1", True)
        self.assertEqual(self.state()["designs"]["login/gui/v1"], {"accepted": True, "comments": []})
        left = [p.name for p in review.state_path(self.folder).parent.iterdir() if p.name.startswith(".state-")]
        self.assertEqual(left, [])
        self.assertTrue(review.state_path(self.folder).read_text().endswith("}\n"))

    def test_accepting_clears_the_siblings_of_the_same_kind_only(self):
        review.set_accepted(self.folder, "login/flow/v1", True)
        review.set_accepted(self.folder, "login/gui/v1", True)
        designs = review.set_accepted(self.folder, "login/gui/v2", True)
        self.assertFalse(designs["login/gui/v1"]["accepted"])
        self.assertTrue(designs["login/gui/v2"]["accepted"])
        self.assertTrue(designs["login/flow/v1"]["accepted"])
        designs = review.set_accepted(self.folder, "login/gui/v2", False)
        self.assertFalse(designs["login/gui/v2"]["accepted"])

    def test_comments_add_anchor_and_delete(self):
        review.add_comment(self.folder, "login/gui/v2", "  too wide ", anchor="screen.html", now=NOW)
        designs = review.add_comment(self.folder, "login/gui/v2", "ok", by="claude", now=NOW)
        comments = designs["login/gui/v2"]["comments"]
        self.assertEqual(comments[0], {"at": "2026-10-18T12:00:00Z", "by": "user", "text": "too wide",
                                       "anchor": "screen.html"})
        self.assertEqual(comments[1]["by"], "claude")
        self.assertNotIn("anchor", comments[1])
        with self.assertRaises(review.ReviewError) as stale:
            review.delete_comment(self.folder, "login/gui/v2", 0, at="2020")
        self.assertEqual(stale.exception.code, 409)
        designs = review.delete_comment(self.folder, "login/gui/v2", 0, at="2026-10-18T12:00:00Z")
        self.assertEqual([c["text"] for c in designs["login/gui/v2"]["comments"]], ["ok"])
        with self.assertRaises(review.ReviewError) as gone:
            review.delete_comment(self.folder, "login/gui/v2", 5)
        self.assertEqual(gone.exception.code, 404)

    def test_ids_and_values_are_validated(self):
        for bad in ("../x/gui/v1", "login/gui", "login/gui/v0", "login/gui/v1/", None, 7):
            with self.assertRaises(review.ReviewError, msg=bad):
                review.set_accepted(self.folder, bad, True)
        with self.assertRaises(review.ReviewError) as unknown:
            review.set_accepted(self.folder, "login/gui/v9", True)
        self.assertEqual(unknown.exception.code, 404)
        for args in ({"accepted": "yes"}, {"accepted": 1}):
            with self.assertRaises(review.ReviewError):
                review.set_accepted(self.folder, "login/gui/v1", args["accepted"])
        for text in ("", "   ", None, 5, "x" * (review.MAX_TEXT + 1)):
            with self.assertRaises(review.ReviewError, msg=repr(text)[:20]):
                review.add_comment(self.folder, "login/gui/v1", text)
        with self.assertRaises(review.ReviewError):
            review.add_comment(self.folder, "login/gui/v1", "x", anchor="a" * 300)
        with self.assertRaises(review.ReviewError):
            review.delete_comment(self.folder, "login/gui/v1", True)
        self.assertFalse(review.state_path(self.folder).exists())

    def test_a_broken_state_file_is_refused_not_overwritten(self):
        path = review.state_path(self.folder)
        path.write_text("{not json")
        with self.assertRaises(review.ReviewError):
            review.set_accepted(self.folder, "login/gui/v1", True)
        self.assertEqual(path.read_text(), "{not json")

    def test_unknown_keys_survive_a_write(self):
        review.state_path(self.folder).write_text(json.dumps({"schema": 1, "note": "keep", "designs": {
            "login/gui/v1": {"accepted": False, "comments": [{"at": "a", "by": "b", "text": "c"}], "extra": 1}}}))
        review.set_accepted(self.folder, "login/gui/v1", True)
        data = self.state()
        self.assertEqual(data["note"], "keep")
        self.assertEqual(data["designs"]["login/gui/v1"]["extra"], 1)
        self.assertEqual(len(data["designs"]["login/gui/v1"]["comments"]), 1)

    def test_status_per_feat_and_kind(self):
        review.set_accepted(self.folder, "login/gui/v1", True)
        review.add_comment(self.folder, "login/gui/v2", "next", now=NOW)
        data = review.status(self.folder)
        self.assertEqual(data["counts"], {"designs": 3, "accepted": 1, "comments": 1})
        gui, flow = data["feats"][0]["kinds"]
        self.assertEqual((gui["id"], gui["accepted"], gui["latest"]), ("gui", "login/gui/v1", "login/gui/v2"))
        self.assertIsNone(flow["accepted"])
        self.assertEqual(gui["versions"][1]["comments"][0]["text"], "next")
        self.assertEqual(data["plan"]["name"], "login")

    def test_accepted_lists_paths_and_superseded(self):
        self.assertEqual(review.accepted(self.folder)["accepted"], [])
        review.set_accepted(self.folder, "login/gui/v1", True)
        found = review.accepted(self.folder)["accepted"]
        self.assertEqual([a["id"] for a in found], ["login/gui/v1"])
        self.assertTrue(found[0]["superseded"])
        self.assertEqual(found[0]["files"], [str(self.folder / "design/login/gui/v1/screen.html")])
        self.assertTrue(Path(found[0]["path"]).is_dir())


if __name__ == "__main__":
    unittest.main()
