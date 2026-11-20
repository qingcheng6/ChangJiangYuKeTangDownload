"""Local PDF tests use real downloaded JPEGs; no simulated website success."""
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from PIL import Image
from pypdf import PdfReader

from ykt.browser import Stopped
from ykt.downloader import _atomic_image
from ykt.files import Manifest, image_info
from ykt.pdf_work import PdfWork
from ykt.quiz_export import export_quizzes
from ykt.quiz_pdf import A4, merge_lesson, validate_pdf, verified_pdf, write_pdf
from ykt.recovery import unfinished

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://changjiang.yuketang.cn"


class QuizPdfTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="quiz_pdf_test_", dir=ROOT / ".local")
        self.root = Path(self.temp.name).resolve()
        self.assertIn((ROOT / ".local").resolve(), self.root.parents)
        self.owner = "a" * 64
        self.task = dict(course_id="1", course_name="测试课程", lesson=dict(id="2", courseware_id="3", name="测试课时"))
        fixtures = sorted((ROOT / ".local/phase3_output").rglob("习题_*.jpg"))
        self.jpeg = [p.read_bytes() for p in fixtures[:2]]
        self.assertEqual(len(self.jpeg), 2)
        self.assertNotEqual(self.jpeg[0], self.jpeg[1])
        self.stop = Event()

    def tearDown(self):
        self.assertIn((ROOT / ".local").resolve(), self.root.parents)
        self.temp.cleanup()

    def source(self, sequence=(1, 0, 1)):
        source = Manifest(self.root / "source", self.owner, ORIGIN)
        with source as m:
            lesson = m.lesson(self.task)
            ids = []
            for i, data in enumerate(self.jpeg):
                rid = hashlib.sha256(str(i).encode()).hexdigest()
                record = dict(status="pending", path=None, resource_id=rid, order=i + 1)
                lesson["resources"][rid] = record
                info = image_info(data)
                path = m.output_path(self.task, lesson, record, info, i + 1, rid)
                _atomic_image(m, path, record, data, self.stop)
                record.update(info, status="complete")
                ids.append(rid)
            lesson.update(status="complete", warnings=[], quiz_pages=len(set(sequence)),
                pdf_sequence=[dict(resource_id=ids[i], slide_id=str(i), page=n + 1) for n, i in enumerate(sequence)])
            m.save()
        return source, source.read_existing()["lessons"]["1:2:3"]

    def target(self):
        return Manifest(self.root / "target", self.owner, ORIGIN)

    def test_actual_jpeg_bytes_order_repetition_and_a4(self):
        source, lesson = self.source()
        with self.target() as target:
            result = merge_lesson(target, self.task, source, lesson, self.stop, lambda _: None)
            self.assertEqual(result["status"], "complete")
            path = target.resolve(result["path"])
            self.assertTrue(verified_pdf(target, result))
            reader = PdfReader(path, strict=True)
            self.assertEqual(len(reader.pages), 3)
            for page, index in zip(reader.pages, (1, 0, 1)):
                obj = page["/Resources"]["/XObject"]["/Im0"].get_object()
                self.assertEqual(obj.get_data(), self.jpeg[index])
                self.assertAlmostEqual(float(page.mediabox.width), A4[0], places=3)
            before = (path.read_bytes(), path.stat().st_mtime_ns)
            again = merge_lesson(target, self.task, source, lesson, self.stop, lambda _: None)
            self.assertTrue(again["skipped"])
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_corrupt_pdf_is_rebuilt_not_just_existence_checked(self):
        source, lesson = self.source()
        with self.target() as target:
            result = merge_lesson(target, self.task, source, lesson, self.stop, lambda _: None)
            path = target.resolve(result["path"])
            path.write_bytes(path.read_bytes()[:100])
            self.assertFalse(verified_pdf(target, result))
            rebuilt = merge_lesson(target, self.task, source, lesson, self.stop, lambda _: None)
            self.assertFalse(rebuilt["skipped"])
            self.assertTrue(verified_pdf(target, rebuilt))
            self.assertEqual(path, target.resolve(rebuilt["path"]))

    def test_existing_pdf_validation_honors_stop(self):
        source, lesson = self.source()
        with self.target() as target:
            result = merge_lesson(target, self.task, source, lesson, self.stop, lambda _: None)
            self.stop.set()
            with self.assertRaises(Stopped):
                verified_pdf(target, result, self.stop)

    def test_partial_images_cannot_mark_pdf_complete_and_old_pdf_kept(self):
        source, lesson = self.source()
        with self.target() as target:
            result = merge_lesson(target, self.task, source, lesson, self.stop, lambda _: None)
            path = target.resolve(result["path"])
            before = path.read_bytes()
            lesson["status"] = "failed"
            failed = merge_lesson(target, self.task, source, lesson, self.stop, lambda _: None)
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(path.read_bytes(), before)

    def test_missing_image_blocks_pdf(self):
        source, lesson = self.source()
        source.resolve(next(iter(lesson["resources"].values()))["path"]).unlink()
        with self.target() as target:
            result = merge_lesson(target, self.task, source, lesson, self.stop, lambda _: None)
            self.assertEqual(result["status"], "failed")
            self.assertFalse(list(target.root.rglob("*.pdf")))

    def test_pdf_retry_limit_atomicity_and_images_independent(self):
        source, lesson = self.source()
        image_hashes = {p: p.read_bytes() for p in source.root.rglob("*.jpg")}
        with self.target() as target, patch("ykt.quiz_pdf.write_pdf", side_effect=OSError()) as writer, patch.object(self.stop, "wait", return_value=False):
            result = merge_lesson(target, self.task, source, lesson, self.stop, lambda _: None)
            self.assertEqual(writer.call_count, 3)
            self.assertEqual(result["status"], "failed")
            self.assertFalse(list(target.root.rglob("*.pdf")))
            self.assertFalse(list(target.root.rglob("*.part")))
        self.assertTrue(all(p.read_bytes() == data for p, data in image_hashes.items()))

    def test_pdf_failure_does_not_change_completed_image_status_and_can_be_selected(self):
        source, lesson = self.source()
        with source as formal, patch("ykt.quiz_pdf.write_pdf", side_effect=OSError()), patch.object(self.stop, "wait", return_value=False):
            result = merge_lesson(formal, self.task, source, lesson, self.stop, lambda _: None)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(formal.data["lessons"]["1:2:3"]["status"], "complete")
        self.assertFalse(unfinished(self.root / "source", self.owner, ORIGIN))
        rows = unfinished(self.root / "source", self.owner, ORIGIN, features={"quiz_pdf"})
        self.assertEqual(len(rows), 1)
        self.assertIn("PDF", rows[0]["reasons"][0])
        with source as formal:
            recovered = merge_lesson(formal, self.task, source, lesson, self.stop, lambda _: None)
            self.assertEqual(recovered["status"], "complete")
            self.assertEqual(formal.data["lessons"]["1:2:3"]["status"], "complete")
        self.assertFalse(unfinished(self.root / "source", self.owner, ORIGIN, features={"quiz_pdf"}))

    def test_stop_before_atomic_replace_preserves_previous_pdf(self):
        source, lesson = self.source()
        with self.target() as target:
            result = merge_lesson(target, self.task, source, lesson, self.stop, lambda _: None)
            path = target.resolve(result["path"])
            before = path.read_bytes()
            target.data["lessons"]["1:2:3"]["quiz_pdf"]["fingerprint"] = "changed"
            def stop_after_write(*args):
                notes = write_pdf(*args)
                self.stop.set()
                return notes
            with patch("ykt.quiz_pdf.write_pdf", side_effect=stop_after_write), self.assertRaises(Stopped):
                merge_lesson(target, self.task, source, lesson, self.stop, lambda _: None)
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(list(target.root.rglob("*.part")))

    def test_no_images_creates_no_empty_pdf_or_lesson_directory(self):
        source, lesson = self.source()
        lesson.update(status="no_images", resources={}, pdf_sequence=[])
        with self.target() as target:
            result = merge_lesson(target, self.task, source, lesson, self.stop, lambda _: None)
            self.assertEqual(result["status"], "no_images")
            self.assertFalse(list(target.root.rglob("*.pdf")))
            self.assertIsNone(target.data["lessons"]["1:2:3"]["directory"])

    def test_transparency_conversion_is_logged_and_lossless_pixels_used(self):
        path = self.root / "alpha.png"
        Image.new("RGBA", (30, 15), (255, 0, 0, 128)).save(path)
        output = self.root / "alpha.pdf"
        notes = write_pdf(output, [path], self.stop)
        self.assertTrue(any("透明通道" in n for n in notes))
        self.assertTrue(validate_pdf(output, 1))
        with Image.open(io.BytesIO(PdfReader(output).pages[0].images[0].data)) as decoded:
            self.assertEqual(decoded.size, (30, 15))
            self.assertEqual(decoded.convert("RGB").getpixel((0, 0)), (255, 127, 127))

    def test_pdf_only_work_resume_cleanup_never_deletes_history(self):
        source, _ = self.source()
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in source.root.rglob("*.jpg")}
        with PdfWork(self.root / "site", "local-test", self.task, self.owner, ORIGIN) as work:
            work.seed(source)
            directory = work.root
            self.assertTrue(list(directory.rglob("*.jpg")))
        self.assertTrue(directory.exists())
        with PdfWork(self.root / "site", "local-test", self.task, self.owner, ORIGIN) as again:
            self.assertEqual(again.root, directory)
            again.discard = True
        self.assertFalse(directory.exists())
        self.assertTrue(all((p.read_bytes(), p.stat().st_mtime_ns) == data for p, data in before.items()))

    def test_valid_pdf_only_run_does_not_fetch_or_create_temporary_images(self):
        source, lesson = self.source()
        with self.target() as target:
            merge_lesson(target, self.task, source, lesson, self.stop, lambda _: None)
        request = dict(tasks=[self.task], owner=self.owner, directory=self.root / "target",
                       options=dict(quiz_images=False, quiz_pdf=True))
        with patch("ykt.quiz_export.verify_account"), patch("ykt.quiz_export.download") as dl, patch("ykt.quiz_export.PdfWork") as work:
            result = export_quizzes(None, None, ORIGIN, request, self.root / "site", "local-test", "legacy",
                self.stop, lambda _: None, lambda *args: None, lambda *args: None, lambda _: None)
            self.assertEqual(result["success"], 1)
            dl.assert_not_called()
            work.assert_not_called()


if __name__ == "__main__":
    unittest.main()
