"""Selection and real Tk tests using the previously verified live course cache."""

import threading
import tkinter as tk
import unittest
from pathlib import Path

from ykt.gui import CourseApp
from ykt.selection import CourseSelection
from ykt.storage import read_json
from ykt.worker import ScanWorker

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / ".local" / "changjiang.yuketang.cn"


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.data = read_json(SITE / "courses.json")
        self.model = CourseSelection()
        self.model.replace(self.data)
        self.course = next(c for c in self.data["courses"] if len(c["lessons"]) > 1)
        self.cid = str(self.course["id"])
        self.key = (self.cid, str(self.course["lessons"][0]["id"]))

    def test_child_parent_and_global_states(self):
        self.assertEqual(self.model.course_state(self.cid), "unchecked")
        self.model.toggle_lesson(self.key)
        self.assertEqual(self.model.course_state(self.cid), "partial")
        self.model.toggle_course(self.cid)
        self.assertEqual(self.model.course_state(self.cid), "checked")
        self.assertEqual(len(self.model.selected), len(self.course["lessons"]))
        self.model.toggle_course(self.cid)
        self.assertFalse(self.model.selected)
        self.model.select_all()
        self.assertEqual(len(self.model.tasks()), sum(len(c["lessons"]) for c in self.data["courses"]))
        self.model.clear()
        self.assertFalse(self.model.tasks())

    def test_order_refresh_and_same_name_classes(self):
        lessons = self.course["lessons"]
        self.model.toggle_lesson((self.cid, str(lessons[-1]["id"])))
        self.model.toggle_lesson(self.key)
        self.assertEqual([task["lesson"]["id"] for task in self.model.tasks()],
                         [lessons[0]["id"], lessons[-1]["id"]])
        self.model.replace(read_json(SITE / "courses.json"))
        self.assertEqual(len(self.model.selected), 2)
        siblings = [c for c in self.data["courses"] if c["name"] == "高等数学A1"]
        self.assertGreater(len(siblings), 1)
        self.assertEqual(len({c["id"] for c in siblings}), len(siblings))

    def test_empty_courses_cannot_add_phantom_lessons(self):
        empty = next(c for c in self.data["courses"] if not c["lessons"])
        self.model.toggle_course(str(empty["id"]))
        self.assertFalse(self.model.selected)
        with self.assertRaises(ValueError):
            self.model.toggle_lesson((str(empty["id"]), self.key[1]))

    def test_queue_snapshot_does_not_share_mutable_records(self):
        worker = ScanWorker("https://changjiang.yuketang.cn", SITE)
        worker.post("progress", self.data)
        _, snapshot = worker.events.get_nowait()
        original = snapshot["courses"][0]["name"]
        self.data["courses"][0]["name"] = ""
        self.assertEqual(snapshot["courses"][0]["name"], original)

    def test_refresh_preserves_selection_for_not_yet_rescanned_courses(self):
        partial = read_json(SITE / "stop_probe.json")
        missing = next(c for c in self.data["courses"] if c["lessons"] and
                       not next(p for p in partial["courses"] if p["id"] == c["id"])["lessons"])
        key = (str(missing["id"]), str(missing["lessons"][0]["id"]))
        self.model.toggle_lesson(key)
        self.model.replace(partial)
        self.assertNotIn(key, self.model.selected)
        self.model.replace(self.data)
        self.assertIn(key, self.model.selected)


class TkTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = CourseApp(self.root, ROOT)
        self.root.update_idletasks()

    def tearDown(self):
        self.root.destroy()

    def test_real_cache_tree_and_checkbox_rendering(self):
        app = self.app
        self.assertEqual(len(app.tree.get_children()), len(app.catalog["courses"]))
        course = next(c for c in app.catalog["courses"] if len(c["lessons"]) > 1)
        cid = str(course["id"])
        key = (cid, str(course["lessons"][0]["id"]))
        app.toggle(app.lesson_iid(key))
        self.assertEqual(app.selection.course_state(cid), "partial")
        self.assertEqual(app.tree.set(app.course_iid(cid), "selected"),
                         "1 / {}".format(len(course["lessons"])))
        self.assertEqual(app.tree.item(app.course_iid(cid), "image"),
                         (str(app.images["partial"]),))
        app.load_cache()
        self.assertIn(key, app.selection.selected)
        app.select_all()
        self.assertEqual(len(app.selection.selected), sum(len(c["lessons"]) for c in app.catalog["courses"]))
        app.clear_selection()
        self.assertFalse(app.selection.selected)
        self.assertTrue(app.download_button.instate(("disabled",)))
        self.assertFalse(app.callback_errors)

    def test_main_thread_guard(self):
        errors = []
        def attempt():
            try:
                self.app._assert_ui()
            except RuntimeError:
                errors.append("guarded")
        thread = threading.Thread(target=attempt)
        thread.start()
        thread.join()
        self.assertEqual(errors, ["guarded"])

    def test_minimum_layout_and_expansion(self):
        self.root.geometry("900x620")
        self.root.deiconify()
        # Process the actual Windows map/resize event, not just idle layout work.
        self.root.update()
        label = self.app.status_label
        self.assertLessEqual(label.winfo_rooty() + label.winfo_height(),
                             self.root.winfo_rooty() + self.root.winfo_height())
        self.assertGreater(self.app.tree.winfo_height(), 30)
        self.app.expand_all(True)
        self.assertTrue(all(self.app.tree.item(iid, "open")
                            for iid in self.app.tree.get_children()))
        self.app.expand_all(False)
        self.assertFalse(any(self.app.tree.item(iid, "open")
                             for iid in self.app.tree.get_children()))


if __name__ == "__main__":
    unittest.main()
