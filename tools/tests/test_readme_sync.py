"""The README's generated regions must match the tree."""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import readme_sync  # noqa: E402


class ReadmeSyncTests(unittest.TestCase):
    def test_readme_is_current(self):
        with open(readme_sync.README, encoding="utf-8") as handle:
            current = handle.read()
        self.assertEqual(
            readme_sync.sync(current), current,
            "README.md is stale: run python3 tools/readme_sync.py")

    def test_every_component_is_described(self):
        readme_sync.render_components()  # raises on a missing or stale entry

    def test_purpose_takes_first_sentence(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("# x\n\n## Purpose\nFirst one. Second one.\n\n## Requirements\n")
        self.addCleanup(os.unlink, f.name)
        self.assertEqual(readme_sync._purpose(f.name), "First one.")


if __name__ == "__main__":
    unittest.main()
