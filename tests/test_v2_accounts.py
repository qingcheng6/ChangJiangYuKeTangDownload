"""Local config/lifecycle tests; these do not claim real website acceptance."""
import tempfile
import threading
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from ykt.accounts import Accounts
from ykt.files import Manifest
from ykt.browser import open_browser, NeedsHuman
from ykt.gui import CourseApp
from ykt.locking import LocalLock, BusyError
from ykt.storage import read_json, write_json
from ykt.tasks import TaskLedger, task_key
from ykt.worker import ScanWorker

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://changjiang.yuketang.cn"


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / ".local", prefix="v2_account_test_")
        self.root = Path(self.temp.name).resolve()
        self.assertIn((ROOT / ".local").resolve(), self.root.parents)
        (self.root / ".local/changjiang.yuketang.cn").mkdir(parents=True)
        self.store = Accounts(self.root, ORIGIN)

    def tearDown(self):
        self.assertIn((ROOT / ".local").resolve(), self.root.parents)
        self.temp.cleanup()

    def test_in_place_legacy_registration_and_reopen(self):
        row = self.store.get()
        site = self.store.site_dir(row)
        self.assertEqual(site, self.root / ".local/changjiang.yuketang.cn")
        file = site / "browser/session-test-file"
        file.parent.mkdir(parents=True)
        file.write_bytes(b"local test fixture, not credentials")
        other = Accounts(self.root, ORIGIN)
        self.assertEqual(other.get()["id"], row["id"])
        self.assertEqual(file.read_bytes(), b"local test fixture, not credentials")

    def test_isolation_rename_and_binding(self):
        a, b = self.store.add("同名"), self.store.add("同名")
        self.assertNotEqual(a["id"], b["id"])
        self.assertNotEqual(self.store.site_dir(a), self.store.site_dir(b))
        path = self.store.image_directory(a, self.root)
        self.store.rename(a["id"], "新名称")
        self.assertEqual(path, self.store.image_directory(self.store.get(a["id"]), self.root))
        self.store.bind(a["id"], "a" * 64)
        with self.assertRaises(ValueError):
            self.store.bind(a["id"], "b" * 64)
        self.assertIsNone(self.store.get(b["id"])["owner"])

    def test_delete_leased_profile_refused_and_downloads_kept(self):
        row = self.store.add("删除单元测试")
        site = self.store.site_dir(row)
        image = self.store.image_directory(row, self.root) / "course/lesson/test.bin"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"preserve download")
        with LocalLock(site / ".browser.lock"):
            with self.assertRaises(BusyError):
                self.store.delete(row["id"])
        (site / "browser").mkdir()
        (site / "browser/test.bin").write_bytes(b"session fixture")
        write_json(site / "courses.json", dict(schema_version=1))
        self.store.delete(row["id"])
        self.assertIsNone(self.store.get(row["id"]))
        self.assertFalse((site / "browser").exists())
        self.assertTrue(image.is_file())

    def test_profile_lease_prevents_second_browser(self):
        row = self.store.add("lease")
        with LocalLock(self.store.site_dir(row) / ".browser.lock"):
            with self.assertRaises(BusyError):
                with LocalLock(self.store.site_dir(row) / ".browser.lock"):
                    pass
            with self.assertRaises(NeedsHuman):
                with open_browser(self.store.site_dir(row) / "browser", lambda _: None):
                    self.fail("Browser must not start while its account lease is held")
        with LocalLock(self.store.site_dir(row) / ".browser.lock"):
            pass

    def test_delete_last_account_does_not_reimport_old_profile(self):
        old = self.store.get()
        self.store.delete(old["id"])
        reopened = Accounts(self.root, ORIGIN)
        self.assertIsNone(reopened.get())
        self.assertFalse(reopened.rows)
        self.assertIsNotNone(reopened.add("重新添加"))

    def test_account_delete_runs_on_worker_thread(self):
        row = self.store.add("后台删除测试")
        site = self.store.site_dir(row)
        (site / "browser").mkdir(parents=True)
        (site / "browser/fixture.bin").write_bytes(b"local fixture")
        worker = ScanWorker(ORIGIN, site, account_id=row["id"])
        self.assertTrue(worker.start_delete(self.root, row["id"]))
        worker.thread.join(3)
        self.assertFalse(worker.running)
        self.assertNotEqual(worker.thread.ident, threading.get_ident())
        events = []
        while not worker.events.empty():
            events.append(worker.events.get_nowait()[0])
        self.assertIn("account_deleted", events)
        self.assertNotIn("error", events)
        self.store.reload()
        self.assertIsNone(self.store.get(row["id"]))

    def test_damaged_registry_preserved(self):
        data = read_json(self.store.path)
        data["accounts"][0]["owner"] = ["invalid"]
        write_json(self.store.path, data)
        before = self.store.path.read_bytes()
        with self.assertRaises(ValueError):
            Accounts(self.root, ORIGIN)
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_feature_keys_and_no_false_pdf_success(self):
        row = self.store.add("features")
        task = dict(course_id="1", course_name="unit", lesson=dict(id="2", name="unit", courseware_id="3"))
        self.assertNotEqual(task_key(row["id"], task, "quiz_images"), task_key(row["id"], task, "quiz_pdf"))
        with TaskLedger(self.store.site_dir(row), row["id"], ORIGIN) as ledger:
            ledger.begin([task], {"quiz_images": True, "quiz_pdf": True})
            self.assertEqual(ledger.counts()["quiz_pdf"]["success"], 0)
            self.assertEqual(ledger.counts()["quiz_pdf"]["failed"], 1)
            ledger.lesson(task, dict(status="no_images", quiz_pages=0))
            self.assertEqual(ledger.counts()["quiz_images"]["success"], 1)
        self.assertEqual(read_json(ledger.path)["account_id"], row["id"])

    def test_v2_layout_keeps_original_manifest_default(self):
        row = self.store.add("新账号")
        task = dict(course_id="1", course_name="CON", lesson=dict(id="2", courseware_id="3", name="unit"))
        selected = self.store.image_directory(row, self.root)
        with Manifest(selected, "a" * 64, ORIGIN, layout="v2") as m:
            lesson = m.lesson(task)
            record = dict(status="pending", path=None)
            path = m.output_path(task, lesson, record, {"extension": ".jpg"}, 1, "b" * 64)
            self.assertEqual(path.parent.name, "习题图片")
            self.assertEqual(m.root, selected)
        self.assertEqual(Manifest(self.root, "a" * 64, ORIGIN).root.name, "雨课堂习题下载")

    def test_gui_switch_waits_for_thread_and_discards_queue(self):
        root = tk.Tk()
        root.withdraw()
        release = threading.Event()
        try:
            app = CourseApp(root, self.root)
            old = app.worker
            target = app.accounts.add("switch")
            old.thread = threading.Thread(target=release.wait)
            old.thread.start()
            old.post("error", "OLD ACCOUNT EVENT")
            with patch.object(app, "start_scan") as start:
                app.switch_account(target["id"])
                self.assertIs(app.worker, old)
                self.assertTrue(old.stop_event.is_set())
                release.set()
                old.thread.join()
                app._poll()
                self.assertIsNot(app.worker, old)
                self.assertEqual(app.account["id"], target["id"])
                self.assertIsNone(app.catalog)
                self.assertNotIn("OLD ACCOUNT EVENT", app.log.get("1.0", "end"))
                start.assert_called_once()
            self.assertTrue(app.export_images.get())
            self.assertFalse(app.export_quiz_pdf.get())
            app.export_images.set(False)
            app.start_download()
            self.assertIn("至少", app.status.get())
            app.export_quiz_pdf.set(True)
            app.start_download()
            self.assertIn("尚未实现PDF", app.status.get())
            self.assertFalse(app.callback_errors)
        finally:
            release.set()
            root.destroy()


if __name__ == "__main__":
    unittest.main()
