"""Regressions use the user's real saved pages, never synthetic course fixtures."""

import ast
import unittest
from pathlib import Path
from threading import Event

from playwright.sync_api import sync_playwright

from ykt import selectors as S
from ykt.browser import Stopped, check_stop
from ykt.scanner import PageChanged, valid_id

ROOT = Path(__file__).resolve().parents[1]


class CoreTests(unittest.TestCase):
    def test_python39_syntax(self):
        for file in [ROOT / "main.py"] + list((ROOT / "ykt").glob("*.py")):
            ast.parse(file.read_text("utf-8"), feature_version=(3, 9))

    def test_identifier_validation(self):
        self.assertEqual(valid_id("1806201338280701440"), "1806201338280701440")
        for value in (None, "undefined", "0", "../1", "-1"):
            with self.assertRaises(PageChanged):
                valid_id(value)

    def test_stop(self):
        event = Event()
        check_stop(event)
        event.set()
        with self.assertRaises(Stopped):
            check_stop(event)


class RealSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)
        cls.page = cls.browser.new_page()
        # Open saved content with no scripts or outbound website requests.
        cls.page.route("**/*", lambda route: route.abort())

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def load(self, name):
        import re
        source = (ROOT / "html" / name).read_text("utf-8")
        source = re.sub(r"<script\b[^>]*>[\s\S]*?</script\s*>", "", source,
                        flags=re.IGNORECASE)
        self.page.set_content(source, wait_until="domcontentloaded")

    def test_real_course_cards(self):
        self.load("雨课堂.html")
        self.assertEqual(self.page.get_by_role("tab", name=S.STUDENT_TAB_NAME).count(), 1)
        cards = self.page.locator(S.COURSE_PANEL).locator(S.COURSE_CARD)
        self.assertEqual(cards.count(), 38)
        self.assertEqual(cards.first.locator(S.COURSE_NAME).inner_text().strip(), "工程经济学")

    def test_hidden_log_panes_are_excluded(self):
        self.load("雨课堂1.html")
        panel = self.page.locator(S.LOG_PANEL)
        visible = panel.locator(S.LOG_LIST)
        self.assertEqual(visible.count(), 1)
        self.assertEqual(visible.locator(S.LOG_TITLE).count(), 20)
        # Same 20 records appear in seven hidden/visible category panes.
        self.assertGreater(panel.locator(S.LOG_TITLE).count(), 20)
        self.assertEqual(visible.locator(S.CLASSROOM_ICON).count(), 20)


if __name__ == "__main__":
    unittest.main()
