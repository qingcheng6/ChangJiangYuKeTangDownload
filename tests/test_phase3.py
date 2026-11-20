"""File-integrity tests use real downloaded images and user-supplied PNG assets."""

import tempfile
import unittest
from pathlib import Path
from threading import Event

from ykt.downloader import _atomic_image, resource_key
from ykt.files import FileProblem, Manifest, image_info, safe_name, units
from ykt.storage import read_json
from ykt import selectors as S

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / ".local" / "changjiang.yuketang.cn"
OUTPUT = ROOT / ".local" / "phase3_output" / "雨课堂习题下载"


class ImageTests(unittest.TestCase):
    def test_actual_formats_and_truncation(self):
        data = next(OUTPUT.rglob("习题_001.jpg")).read_bytes()
        info = image_info(data)
        self.assertEqual((info["format"], info["extension"]), ("JPEG", ".jpg"))
        self.assertEqual((info["width"], info["height"]), (1280, 960))
        png = ROOT / "html" / "雨课堂_files" / "info-i.png"
        self.assertEqual(image_info(png.read_bytes())["extension"], ".png")
        with self.assertRaises(FileProblem):
            image_info(data[:100])

    def test_volatile_authorization_not_part_of_identity(self):
        base = "https://yangtse-pri-ups.yuketang.cn/common_uploads/27602331/cover447_20261028100656.jpg"
        self.assertEqual(resource_key(base + "?auth_key=first"),
                         resource_key(base + "?auth_key=second"))
        self.assertNotEqual(resource_key(base + "?page=1"), resource_key(base + "?page=2"))

    def test_windows_names_and_utf16_budget(self):
        self.assertEqual(safe_name("CON.txt"), "_CON.txt")
        self.assertEqual(safe_name("COM¹.txt"), "_COM¹.txt")
        self.assertEqual(safe_name("LPT2 .txt"), "_LPT2 .txt")
        self.assertEqual(safe_name('a:b/c*?<>|".'), "a_b_c______")
        self.assertLessEqual(units(safe_name("很长的课时😀" * 50, 30)), 30)
        self.assertFalse(safe_name("name. ").endswith((".", " ")))


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="phase3_test_", dir=ROOT / ".local")
        self.directory = Path(self.temporary.name).resolve()
        self.assertIn((ROOT / ".local").resolve(), self.directory.parents)
        self.cache = read_json(SITE / "courses.json")
        c = self.cache["courses"][0]
        self.task = dict(course_id=c["id"], course_name=c["name"], class_name=c["class_name"],
                         lesson=dict(c["lessons"][0]))
        self.data = next(OUTPUT.rglob("习题_001.jpg")).read_bytes()

    def tearDown(self):
        # Only the verified temporary tree inside this workspace is cleaned.
        self.assertIn((ROOT / ".local").resolve(), self.directory.parents)
        self.temporary.cleanup()

    def test_atomic_save_verification_and_collision(self):
        with Manifest(self.directory, self.cache["owner_fingerprint"], self.cache["origin"]) as m:
            l = m.lesson(self.task)
            record = l["resources"].setdefault("actual-resource", dict(status="pending", path=None))
            info = image_info(self.data)
            path = m.output_path(self.task, l, record, info, 1, "a" * 64)
            self.assertFalse(path.parent.exists())
            _atomic_image(m, path, record, self.data, Event())
            self.assertFalse(m.verified(record))  # Atomic file alone is not a completion record.
            record.update(info, status="complete")
            m.save()
            self.assertTrue(m.verified(record))
            collision = m.output_path(self.task, l, {}, info, 1, "b" * 64)
            self.assertNotEqual(path, collision)
            path.write_bytes(self.data[:100])
            self.assertFalse(m.verified(record))
            self.assertFalse(list(path.parent.glob("*.part")))

    def test_manifest_bounds_and_exclusive_lock(self):
        with Manifest(self.directory, self.cache["owner_fingerprint"], self.cache["origin"]) as m:
            with self.assertRaises(FileProblem):
                m.resolve("../../escape.jpg")
            with self.assertRaises(FileProblem):
                with Manifest(self.directory, self.cache["owner_fingerprint"], self.cache["origin"]):
                    pass


class RealQuizSnapshotTests(unittest.TestCase):
    def test_only_real_filtered_quiz_region_is_collected(self):
        import re
        from playwright.sync_api import sync_playwright
        snapshot = ROOT / "html" / "雨课堂2_files" / "1806201338280701440.html"
        source = re.sub(r"<script\b[^>]*>[\s\S]*?</script\s*>", "",
                        snapshot.read_text("utf-8"), flags=re.IGNORECASE)
        source = source.replace("<head>", '<head><base href="' + snapshot.parent.as_uri() + '/">', 1)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.route("**/*", lambda route: route.abort())
            page.set_content(source, wait_until="domcontentloaded")
            items = page.locator(S.QUIZ_ITEMS)
            self.assertEqual(items.count(), 14)
            self.assertGreater(page.locator("img").count(), 14)
            for index in range(items.count()):
                data = items.nth(index).evaluate(S.QUIZ_RESOURCE_DATA)
                self.assertEqual(len(data["resources"]), 1)
                self.assertFalse(data["unsupported"])
                self.assertTrue(any("cover" in url for url in data["resources"][0]["candidates"]))
            browser.close()
