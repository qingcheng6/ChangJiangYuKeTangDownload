"""Portable archive tests. Local image fixtures do not represent a live site."""
import io
import tempfile
import tkinter as tk
import unittest
from contextlib import ExitStack
from pathlib import Path
from threading import Event
from unittest.mock import patch

from PIL import Image

from ykt.downloader import download
from ykt.files import FileProblem, Manifest, units
from ykt.gui import CourseApp
from ykt.quiz_export import export_quizzes
from ykt.quiz_pdf import pdf_path
from ykt.recovery import unfinished
from ykt.resource_export import export_resources

ORIGIN = "https://changjiang.yuketang.cn"


class LocalStop(Event):
    # These local boundary tests have no website traffic to rate-limit.
    def wait(self, timeout=None):
        return self.is_set()


class Page:
    def is_closed(self):
        return False


class FlatLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ykt_v21_")
        self.root = Path(self.temp.name).resolve()
        self.owner = "a" * 64
        self.task = dict(course_id="1", course_name="课程", lesson=dict(id="2", courseware_id="3", name="课时01"))
        self.stop = LocalStop()
        stream = io.BytesIO()
        Image.new("RGB", (64, 48), "navy").save(stream, "JPEG")
        self.jpeg = stream.getvalue()
        self.resources = [dict(candidates=["https://local.invalid/image"], slide_id="10", page=1)]
        self.logs = []

    def tearDown(self):
        self.temp.cleanup()

    def run_job(self, output, bits=7, tasks=None, progress=None, empty=False):
        options = dict(quiz_images=bool(bits & 1), quiz_pdf=bool(bits & 2), courseware_pdf=bool(bits & 4))
        request = dict(tasks=tasks or [self.task], directory=output, owner=self.owner, options=options)
        resources = [] if empty else self.resources
        with ExitStack() as stack:
            for module in ("downloader", "quiz_export", "resource_export"):
                stack.enter_context(patch("ykt." + module + ".verify_account"))
            stack.enter_context(patch("ykt.downloader.extract_lesson", return_value=dict(resources=resources, unsupported=[], pages=len(resources))))
            stack.enter_context(patch("ykt.courseware.extract_courseware", return_value=resources))
            stack.enter_context(patch("ykt.downloader._fetch", return_value=self.jpeg))
            stack.enter_context(patch("ykt.courseware._fetch", return_value=self.jpeg))
            args = (None, Page(), ORIGIN, request, self.root / "site", "local-test", "flat", self.stop,
                    self.logs.append, lambda *_: None, lambda *_: None, progress or (lambda _: None))
            if bits & 4:
                return export_resources(*args)
            if bits & 2:
                return export_quizzes(*args)
            return download(None, Page(), ORIGIN, request["tasks"], output, self.owner, self.stop,
                            self.logs.append, on_progress=progress, layout="flat")

    def test_seven_modes_exact_flat_paths_and_verified_repeat(self):
        for bits in range(1, 8):
            with self.subTest(bits=bits):
                output = self.root / str(bits)
                result = self.run_job(output, bits)
                self.assertEqual(result["success"], 1)
                expected = set()
                if bits & 1:
                    expected.add("课程/习题图片/课时01/习题_001.jpg")
                if bits & 2:
                    expected.add("课程/课时01_习题合集.pdf")
                if bits & 4:
                    expected.add("课程/课时01_课件.pdf")
                products = {p.relative_to(output).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                            for p in output.rglob("*") if p.suffix in (".jpg", ".pdf")}
                self.assertEqual(set(products), expected)
                self.assertEqual([p.name for p in output.iterdir() if p.is_dir()], ["课程"])
                self.assertEqual((output / "课程/习题图片").exists(), bool(bits & 1))
                self.assertEqual(self.run_job(output, bits)["downloaded"], 0)
                for relative, old in products.items():
                    path = output / relative
                    self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), old)
                self.assertFalse(list(output.rglob("*.part")))

    def test_same_names_case_and_sanitized_collisions_reserve_pdf_only_names(self):
        tasks = [dict(self.task, lesson=dict(self.task["lesson"], name="A:B")),
                 dict(self.task, lesson=dict(self.task["lesson"], id="4", name="a?b")),
                 dict(self.task, course_id="5", lesson=dict(self.task["lesson"], name="A:B"))]
        output = self.root / "same"
        result = self.run_job(output, 6, tasks)
        self.assertEqual(result["success"], 3)
        self.assertEqual(len(list(output.rglob("*.pdf"))), 6)
        self.assertFalse(list(output.rglob("习题图片")))
        m = Manifest(output, self.owner, ORIGIN, layout="flat")
        data = m.read_existing()
        self.assertEqual(len(set(data["courses"].values())), 2)
        paths = [row[f]["path"].casefold() for row in data["lessons"].values() for f in ("quiz_pdf", "courseware_pdf")]
        self.assertEqual(len(set(paths)), 6)
        self.assertEqual(self.run_job(output, 6, tasks)["success"], 3)

    def test_legacy_and_v2_files_and_indexes_not_modified(self):
        output = self.root / "history"
        with patch("ykt.downloader.verify_account"), patch("ykt.downloader.extract_lesson", return_value=dict(
                resources=self.resources, unsupported=[], pages=1)), patch("ykt.downloader._fetch", return_value=self.jpeg):
            for layout in ("legacy", "v2"):
                download(None, Page(), ORIGIN, [self.task], output, self.owner, self.stop, self.logs.append, layout=layout)
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in output.rglob("*") if p.is_file()}
        self.assertEqual(self.run_job(output)["downloaded"], 1)
        for path, old in before.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), old)
        flat = Manifest(output, self.owner, ORIGIN, layout="flat")
        self.assertNotEqual(flat.path, Manifest(output, self.owner, ORIGIN, layout="v2").path)
        self.assertEqual(len(list(output.rglob("*.jpg"))), 3)

    def test_empty_resources_create_no_course_or_image_folder(self):
        for bits in range(1, 8):
            output = self.root / str(bits)
            self.assertEqual(self.run_job(output, bits, empty=True)["success"], 1)
            self.assertFalse([p for p in output.iterdir() if p.is_dir()])
            self.assertFalse(list(output.rglob("*.pdf")))

    def test_stop_pending_resume_corrupt_image_and_pdfs(self):
        output = self.root / "resume"
        future = dict(self.task, lesson=dict(self.task["lesson"], id="4", name="课时02"))
        tasks = [self.task, future]
        def progress(value):
            if value["downloaded"]:
                self.stop.set()
        self.assertEqual(self.run_job(output, tasks=tasks, progress=progress)["status"], "stopped")
        self.assertEqual(len(unfinished(output, self.owner, ORIGIN, layout="flat", features=["quiz_pdf", "courseware_pdf"])), 2)
        self.stop.clear()
        self.assertEqual(self.run_job(output, tasks=tasks)["success"], 2)
        originals = {p: p.read_bytes() for p in output.rglob("*") if p.suffix in (".jpg", ".pdf")}
        for path, data in originals.items():
            path.write_bytes(data[:10])
        self.assertEqual(self.run_job(output, tasks=tasks)["downloaded"], 2)
        for path, data in originals.items():
            self.assertEqual(path.read_bytes(), data)

    def test_unknown_pdf_reserved_names_long_paths_and_other_owner(self):
        output = self.root / "safe"
        task = dict(self.task, course_name="CON", lesson=dict(self.task["lesson"], name='A/B:*?"<>|'))
        with Manifest(output, self.owner, ORIGIN, layout="flat") as m:
            row = m.lesson(task)
            parent = m.pdf_directory_for(task, row)
            parent.mkdir(parents=True)
            unknown = pdf_path(m, task, row, {})
            unknown.write_bytes(b"unknown user file")
            chosen = pdf_path(m, task, row, {})
            self.assertNotEqual(unknown, chosen)
            self.assertEqual(unknown.read_bytes(), b"unknown user file")
            self.assertEqual(parent.name, "_CON")
            self.assertLessEqual(units(chosen), 240)
            m.save()
        other = Manifest(output, "b" * 64, ORIGIN, layout="flat")
        with other:
            other_parent = other.pdf_directory_for(task, other.lesson(task))
            self.assertNotEqual(other_parent, parent)
        with self.assertRaises(FileProblem):
            Manifest(output / ("很长" * 150), self.owner, ORIGIN, layout="flat")

    def test_gui_routes_old_and_new_accounts_to_selected_root(self):
        project = self.root / "project"
        (project / ".local" / "changjiang.yuketang.cn").mkdir(parents=True)
        window = tk.Tk()
        try:
            app = CourseApp(window, project)
            self.assertEqual(app.worker.layout, "flat")
            self.assertEqual(app.accounts.image_directory(app.account, self.root, layout=app.worker.layout), self.root)
            row = app.accounts.add("另一个账号")
            self.assertEqual(app.accounts.image_directory(row, self.root, layout="flat"), self.root)
            # Existing consumers can still explicitly read historical layouts.
            self.assertNotEqual(app.accounts.image_directory(row, self.root), self.root)
            app.root.update_idletasks()
            self.assertEqual(app.callback_errors, [])
        finally:
            window.destroy()


if __name__ == "__main__":
    unittest.main()
