"""Portable checks: no private account cache, snapshots or downloaded fixtures.

These checks do not replace the separately recorded real website acceptance.
"""

import ast
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from bootstrap import pinned_requirements
from ykt.files import FileProblem, Manifest, safe_name, units
from ykt.gui import CourseApp
from ykt.storage import read_json, write_json

ROOT = Path(__file__).resolve().parents[1]


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / ".local"
        parent.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="delivery_test_", dir=parent)
        self.directory = Path(self.temp.name).resolve()
        self.assertIn(parent.resolve(), self.directory.parents)

    def tearDown(self):
        self.assertIn((ROOT / ".local").resolve(), self.directory.parents)
        self.temp.cleanup()

    def test_all_production_code_has_python39_syntax(self):
        for path in [ROOT / "main.py", ROOT / "bootstrap.py"] + list((ROOT / "ykt").glob("*.py")):
            ast.parse(path.read_text("utf-8"), feature_version=(3, 9))

    def test_pinned_dependency_file(self):
        self.assertEqual(pinned_requirements(ROOT / "requirements.txt"),
                         [("playwright", "1.56.0"), ("Pillow", "11.3.0"), ("pypdf", "6.21.4")])

    def test_corrupt_storage_is_not_accepted_as_a_valid_cache(self):
        path = self.directory / "bad.json"
        path.write_text("[]", encoding="utf-8")
        with self.assertRaises(ValueError):
            read_json(path)
        self.assertEqual(path.read_text("utf-8"), "[]")

    def test_bad_manifest_is_preserved_and_lock_is_released(self):
        owner = "a" * 64
        m = Manifest(self.directory, owner, "https://changjiang.yuketang.cn")
        m.root.mkdir()
        damaged = dict(schema_version=1, owner=owner, origin=m.origin, courses={},
                       lessons={"broken": {"resources": []}})
        write_json(m.path, damaged)
        original = m.path.read_bytes()
        with self.assertRaises(FileProblem):
            with m:
                pass
        self.assertEqual(m.path.read_bytes(), original)
        self.assertIsNone(m.lock)

    def test_windows_name_budget_and_overlong_root(self):
        self.assertEqual(safe_name("CON .txt"), "_CON .txt")
        self.assertLessEqual(units(safe_name("😀很长" * 80, 22)), 22)
        with self.assertRaises(FileProblem):
            Manifest(self.directory / ("很长" * 100), "b" * 64, "https://changjiang.yuketang.cn")

    def test_clean_gui_without_any_private_cache(self):
        root = tk.Tk()
        root.withdraw()
        try:
            app = CourseApp(root, self.directory)
            self.assertIsNone(app.catalog)
            self.assertEqual(app.tree.get_children(), ())
            self.assertTrue(app.download_button.instate(("disabled",)))
            self.assertFalse(app.worker.running)
            self.assertFalse(app.callback_errors)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
