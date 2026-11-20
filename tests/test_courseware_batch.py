"""Regression structures confirmed in real reports; not simulated site acceptance."""
import unittest
import io
import hashlib
import tempfile
from pathlib import Path
from threading import Event
from unittest.mock import patch
from pypdf import PdfReader
from PIL import Image

from ykt.courseware import ordered_slides, preview_matches, verified_courseware
from ykt.browser import PageChanged
from ykt.files import Manifest
from ykt.resource_export import export_resources
from ykt.extractor import _wait_state


def slide(sid, page, deck='100', **extra):
    return dict(slide_id=str(sid), page=page, presentation_id=deck,
                visible=True, kind='slide', **extra)


class CoursewareBatchTests(unittest.TestCase):
    def test_page_numbers_are_scoped_to_each_actual_presentation(self):
        rows = [slide(12, 2), slide(11, 1), slide(21, 1, '200'), slide(22, 2, '200'), slide(11, 1)]
        self.assertEqual([s['slide_id'] for _, s in ordered_slides(rows)], ['11', '12', '21', '22'])

    def test_static_capture_without_slide_id_remains_after_its_source_page(self):
        rows = [slide(11, 1), dict(slide_id='undefined', page=None, kind='capture', visible=None, dt=1234),
                slide(12, 2), dict(slide_id='undefined', page=None, kind='capture', visible=None, dt=1235),
                dict(slide_id='undefined', page=None, kind='capture', visible=None, dt=1234)]
        self.assertEqual([s['slide_id'] for _, s in ordered_slides(rows)], ['11', 'capture_1234', '12', 'capture_1235'])

    def test_preview_capture_ids_are_generated_but_timestamps_are_bound(self):
        rows = [slide(11, 1), dict(slide_id='undefined', kind='capture', visible=None, dt=1234)]
        preview = [slide(11, 1), dict(slide_id='999', kind='capture', visible=None, dt=1234)]
        self.assertTrue(preview_matches(rows, preview))
        self.assertFalse(preview_matches(rows, preview[:1]))
        self.assertFalse(preview_matches(rows, [preview[0], dict(preview[1], dt=1235)]))
        with self.assertRaises(PageChanged):
            preview_matches(rows, [preview[0], dict(preview[1], kind='video')])

    def test_ambiguous_pages_within_one_presentation_still_fail(self):
        with self.assertRaises(PageChanged):
            ordered_slides([slide(11, 1), slide(12, 1)])
        hidden = dict(slide(12, 1), visible=False)
        self.assertEqual([s['slide_id'] for _, s in ordered_slides([slide(11, 1), hidden])], ['11'])

    def test_wait_for_requested_lesson_and_fully_switched_all_tab(self):
        from types import SimpleNamespace
        ready = dict(lesson_id='100', course_id='1', all=3, selected=0, shown=3)
        states = [dict(ready, lesson_id='99'), dict(ready, selected=1, shown=1),
                  dict(ready, shown=1), ready]
        watch = SimpleNamespace(lesson_id='100', detail=True, info=('100','1'), count=3, check=lambda:None)
        class LocalStop(Event):
            def wait(self, timeout=None):
                return self.is_set()
        with patch('ykt.extractor._state', side_effect=states) as state:
            self.assertEqual(_wait_state(None, None, watch, '1', LocalStop(), all_slides=True), ready)
            self.assertEqual(state.call_count, 4)

    def test_ten_lesson_and_two_course_batches_have_independent_pdf_content(self):
        class LocalStop(Event):
            def wait(self, timeout=None):
                return self.is_set()
        origin, owner = 'https://changjiang.yuketang.cn', 'a' * 64
        with tempfile.TemporaryDirectory(prefix='courseware_batch_') as directory:
            root = Path(directory)
            for scenario in ('single', 'multi'):
                tasks = [dict(course_id='1' if scenario == 'single' or i < 5 else '2',
                              course_name='same course', lesson=dict(id=str(i+10), courseware_id=str(i+100), name='same lesson'))
                         for i in range(10)]
                images = {}
                for i, task in enumerate(tasks):
                    buffer = io.BytesIO()
                    Image.new('RGB', (64, 48), (i * 20, 15, 50)).save(buffer, 'JPEG')
                    images[task['lesson']['id']] = buffer.getvalue()
                def extract(_, __, task, *args):
                    lid = task['lesson']['id']
                    return [dict(candidates=['https://local.invalid/' + lid], slide_id=lid, page=1)]
                def fetch(_, resource, *args):
                    return images[resource['slide_id']]
                options = dict(quiz_images=False, quiz_pdf=False, courseware_pdf=True)
                request = dict(tasks=tasks, owner=owner, directory=root/scenario, options=options)
                done = []
                with patch('ykt.resource_export.verify_account'), patch('ykt.courseware.extract_courseware', side_effect=extract), patch('ykt.courseware._fetch', side_effect=fetch):
                    result = export_resources(None, None, origin, request, root/'site', 'test-account', 'flat',
                        LocalStop(), lambda _:None, lambda *_:None, lambda t,f,r:done.append((t,f,r)), lambda _:None)
                self.assertEqual(result['success'], 10)
                self.assertEqual(len(done), 10)
                manifest = Manifest(root/scenario, owner, origin, layout='flat')
                data = manifest.read_existing()
                paths = set()
                for task, feature, metadata in done:
                    self.assertEqual(feature, 'courseware_pdf')
                    self.assertTrue(verified_courseware(manifest, metadata, Event(), task))
                    other = dict(task, lesson=dict(task['lesson'], id='999'))
                    self.assertFalse(verified_courseware(manifest, metadata, Event(), other))
                    self.assertFalse(verified_courseware(manifest, dict(metadata, version=1), Event(), task))
                    path = manifest.resolve(metadata['path'])
                    paths.add(path)
                    page = PdfReader(path).pages[0]
                    raw = page['/Resources']['/XObject']['/Im0'].get_object().get_data()
                    self.assertEqual(hashlib.sha256(raw).digest(), hashlib.sha256(images[task['lesson']['id']]).digest())
                    self.assertEqual(path.parent, manifest.resolve(data['courses'][task['course_id']]))
                self.assertEqual(len(paths), 10)


if __name__ == '__main__':
    unittest.main()
