"""The design store (hal2 plan 0364, D3, D6, D8): plan folder and title, feat/kind/version order, new versions."""
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import store  # noqa: E402

NOW = dt.datetime(2026, 10, 18, 12, 0, tzinfo=dt.timezone.utc)


def make_plan(root: Path, slug: str, plan_md: str | None = None, spec_md: str | None = None) -> Path:
    folder = root / "plans" / slug
    folder.mkdir(parents=True)
    if plan_md is not None:
        (folder / "plan.md").write_text(plan_md)
    if spec_md is not None:
        (folder / "spec.md").write_text(spec_md)
    return folder


class PlanFolderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_by_number_slug_and_pointer(self):
        folder = make_plan(self.root, "0042-login-page", "---\ntitle: \"login page\"\n---\n# Plan 0042\n")
        self.assertEqual(store.plan_dir(self.root, "42"), folder)
        self.assertEqual(store.plan_dir(self.root, "0042-login-page"), folder)
        (self.root / "plans" / "CURRENT_PLAN").write_text("0042-login-page\n")
        self.assertEqual(store.plan_dir(self.root, None), folder)

    def test_missing_plan_is_an_error(self):
        (self.root / "plans").mkdir()
        with self.assertRaises(store.StoreError):
            store.plan_dir(self.root, None)
        with self.assertRaises(store.StoreError):
            store.plan_dir(self.root, "7")

    def test_repo_root_walks_up(self):
        make_plan(self.root, "0001-a")
        deep = self.root / "code" / "x"
        deep.mkdir(parents=True)
        self.assertEqual(store.repo_root(deep), self.root.resolve())

    def test_title_from_plan_front_matter(self):
        folder = make_plan(self.root, "0042-login-page", "---\ntype: Plan\ntitle: \"login page v2\"\n---\n")
        self.assertEqual(store.plan_info(folder), {"number": "0042", "slug": "0042-login-page",
                                                   "name": "login page v2"})

    def test_spec_only_folder_takes_the_spec_heading(self):
        folder = make_plan(self.root, "0043-search", spec_md="# Spec 0043: full text search\n\nbody\n")
        self.assertEqual(store.plan_info(folder)["name"], "full text search")

    def test_bare_folder_takes_the_slug(self):
        folder = make_plan(self.root, "0044-dark-mode")
        self.assertEqual(store.plan_info(folder)["name"], "dark mode")


class VersionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = make_plan(Path(self.tmp.name), "0042-login")

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_version_and_meta(self):
        path = store.new_version(self.folder, "login", "gui", title="login screen", base="today's login", now=NOW)
        self.assertEqual(path, self.folder / "design" / "login" / "gui" / "v1")
        meta = store.read_meta(path)
        self.assertEqual(meta["id"], "login/gui/v1")
        self.assertEqual(meta["created"], "2026-10-18T12:00:00Z")
        self.assertEqual((meta["title"], meta["base"], meta["from"]), ("login screen", "today's login", None))

    def test_update_copies_and_keeps_the_old_version(self):
        v1 = store.new_version(self.folder, "login", "gui", title="login screen", now=NOW)
        (v1 / "screen.html").write_text("<p>old</p>")
        v2 = store.new_version(self.folder, "login", "gui", now=NOW)
        self.assertEqual(v2.name, "v2")
        self.assertEqual((v2 / "screen.html").read_text(), "<p>old</p>")
        (v2 / "screen.html").write_text("<p>new</p>")
        self.assertEqual((v1 / "screen.html").read_text(), "<p>old</p>")
        meta = store.read_meta(v2)
        self.assertEqual((meta["from"], meta["title"]), ("v1", "login screen"))
        self.assertEqual(store.versions(self.folder, "login", "gui"), [1, 2])

    def test_versions_sort_by_number(self):
        for _ in range(11):
            store.new_version(self.folder, "login", "flow", now=NOW)
        self.assertEqual(store.versions(self.folder, "login", "flow"), list(range(1, 12)))

    def test_names_must_be_kebab_case(self):
        for feat, kind in (("Login", "gui"), ("login", "a b"), ("../x", "gui")):
            with self.assertRaises(store.StoreError):
                store.new_version(self.folder, feat, kind)

    def test_feat_order_from_feats_json_then_folders(self):
        for feat in ("zeta", "alpha", "mid"):
            store.new_version(self.folder, feat, "gui", now=NOW)
        self.assertEqual(store.feats(self.folder), ["alpha", "mid", "zeta"])
        (self.folder / "design" / "feats.json").write_text(json.dumps(["zeta", "gone"]))
        self.assertEqual(store.feats(self.folder), ["zeta", "alpha", "mid"])
        store.new_version(self.folder, "beta", "gui", now=NOW)
        self.assertEqual(json.loads((self.folder / "design" / "feats.json").read_text()), ["zeta", "gone", "beta"])

    def test_kind_order_known_kinds_first(self):
        for kind in ("zzz", "erd", "flow", "gui", "aaa"):
            store.new_version(self.folder, "login", kind, now=NOW)
        self.assertEqual(store.kinds(self.folder, "login"), ["gui", "flow", "erd", "aaa", "zzz"])

    def test_files_current_before_new_and_meta_left_out(self):
        v1 = store.new_version(self.folder, "login", "erd", now=NOW)
        for name in ("new.dbml", "current.dbml", "notes.md"):
            (v1 / name).write_text("x")
        self.assertEqual([f.name for f in store.files(v1)], ["current.dbml", "new.dbml", "notes.md"])

    def test_state_is_read_tolerantly(self):
        self.assertEqual(store.read_state(self.folder), {})
        (self.folder / "design").mkdir(exist_ok=True)
        state = self.folder / "design" / "state.json"
        state.write_text("{broken")
        self.assertEqual(store.read_state(self.folder), {})
        state.write_text(json.dumps({"schema": 1, "designs": {"login/gui/v1": {"accepted": True}}}))
        self.assertEqual(store.read_state(self.folder), {"login/gui/v1": {"accepted": True}})


if __name__ == "__main__":
    unittest.main()
