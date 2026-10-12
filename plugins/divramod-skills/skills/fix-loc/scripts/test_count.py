import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import count  # noqa: E402

RUST = """\
/// A documented function.
pub fn add(a: i32, b: i32) -> i32 {
    // a comment
    a + b
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn adds() {
        let braces = "{ not a block";
        assert_eq!(add(1, 2), 3, "{}", braces);
    }
}
"""


class RustTestLines(unittest.TestCase):
    def test_a_trailing_test_module_is_counted_with_its_attribute(self):
        # #[cfg(test)], mod tests {, use, #[test], fn adds() {, let, assert, }, } = 9 code lines
        self.assertEqual(count.rust_test_lines(RUST), 9)

    def test_a_file_without_tests_has_none(self):
        self.assertEqual(count.rust_test_lines("fn a() {}\n"), 0)

    def test_a_test_module_file_declaration_is_one_line(self):
        self.assertEqual(count.rust_test_lines("fn a() {}\n#[cfg(test)]\nmod tests;\n"), 0)

    def test_code_after_the_test_module_still_counts(self):
        text = "#[cfg(test)]\nmod t {\n    fn x() {}\n}\nfn after() {}\n"
        self.assertEqual(count.rust_test_lines(text), 4)


@unittest.skipIf(shutil.which("scc") is None, "scc is not installed")
class CodeLines(unittest.TestCase):
    def test_only_production_code_lines_count(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "lib.rs").write_text(RUST)
            Path(root, "a.py").write_text('"""Docstring."""\n# comment\n\ndef a():\n    return 1\n')
            Path(root, "notes.md").write_text("# not source\n")
            counts = count.code_lines(root, ["lib.rs", "a.py", "notes.md"])
        # lib.rs: pub fn, a + b, } = 3 production lines; a.py: def, return = 2
        self.assertEqual(counts, {"lib.rs": 3, "a.py": 2})


if __name__ == "__main__":
    unittest.main()
