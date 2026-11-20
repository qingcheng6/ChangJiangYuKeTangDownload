"""Exercise shared layouts through the actual GUI, worker and writers."""
import gc
import io
import tempfile
import tkinter as tk
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from pikepdf import Pdf, PdfImage
from pypdf import PdfReader

from test_answer_workflow import LocalStop, ORIGIN, OWNER, Page
from ykt.answer_images import read_native_answer
from ykt.courseware import verified_courseware
from ykt.files import Manifest
from ykt.gui import CourseApp
from ykt.quiz_grid import courseware_field, field_for
from ykt.recovery import unfinished


class CoursewareGridTests(unittest.TestCase):
    def test_shared_layout_courseware_only_and_combined(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / 'out'
            output.mkdir()
            window = tk.Tk()
            window.withdraw()
            app = None
            try:
                app = CourseApp(window, root)
                self.exercise_gui(app, output)
            finally:
                for callback in window.tk.splitlist(window.tk.call('after', 'info')):
                    window.after_cancel(callback)
                window.destroy()
                del app, window
                gc.collect()

    def exercise_gui(self, app, output):
        colors = [(170+i*7, 205-i*8, 230-i*3) for i in range(7)]
        images = []
        for color in colors:
            stream = io.BytesIO()
            Image.new('RGB', (320, 240), color).save(stream, 'PNG')
            images.append(stream.getvalue())
        slides = [dict(candidates=[f'https://local.invalid/{i}'], slide_id=str(10+i),page=i+1)
                  for i in range(len(images))]
        lessons = [dict(id='2', courseware_id='3',name='课时',created_at=1792080000000)]
        app.catalog = dict(owner_fingerprint=OWNER, courses=[dict(id='1',name='课程',class_name='2026秋',
                                                                  status='complete',lessons=lessons)])
        app.selection.replace(app.catalog)
        app._render_tree()
        app.toggle(app.term_iid('2026秋'))
        app.save_dir.set(str(output))
        app.export_images.set(False)
        app.export_courseware_pdf.set(True)
        app.worker.expected_owner = OWNER
        app.worker.stop_event = LocalStop()
        self.assertFalse(app.more_export.winfo_manager())
        app._toggle_more()
        self.assertEqual(app.more_export.winfo_manager(), 'pack')
        app._toggle_more()

        @contextmanager
        def browser(*args):
            yield None, Page()

        def quiz_extract(*args, answers=False):
            resources = [dict(row) for row in slides[:3]]
            if answers:
                for index, row in enumerate(resources):
                    row['native_answer'] = read_native_answer('正确答案：AB' if index == 0 else '')
            return dict(resources=resources,pages=len(resources),unsupported=[])

        manifest = Manifest(output, OWNER, ORIGIN, layout='flat')
        with ExitStack() as mocks:
            mocks.enter_context(patch('ykt.worker.open_browser', side_effect=browser))
            for module in ('resource_export', 'quiz_export', 'downloader'):
                mocks.enter_context(patch(f'ykt.{module}.verify_account'))
            mocks.enter_context(patch('ykt.courseware.extract_courseware',return_value=slides))
            mocks.enter_context(patch('ykt.downloader.extract_lesson',side_effect=quiz_extract))
            for module in ('courseware', 'downloader'):
                mocks.enter_context(patch(f'ykt.{module}._fetch',
                    side_effect=lambda *args:images[int(args[2].rsplit('/',1)[-1])]))

            def export(orientation, label, counts, combined=False):
                app._update_controls()
                app.paper_radios[orientation=='landscape'].invoke()
                app.grid_box.set(label)
                app.grid_box.event_generate('<<ComboboxSelected>>')
                self.assertFalse(app.export_quiz_pdf.get())
                if combined:
                    app.answer_check.invoke()
                    self.assertTrue(app.export_quiz_pdf.get())
                spec = app._grid_request()
                app.download_button.invoke()
                app.worker.thread.join(30)
                self.assertFalse(app.worker.running)
                events = []
                while not app.worker.events.empty():
                    events.append(app.worker.events.get_nowait())
                self.assertEqual([v['success'] for k,v in events if k=='download_result'],[1],events)
                lesson = next(iter(manifest.read_existing()['lessons'].values()))
                record = lesson[courseware_field(spec)]
                path = manifest.resolve(record['path'])
                self.assertTrue(verified_courseware(manifest,record,LocalStop(),grid=spec))
                self.assertEqual(path.parent, output / '课程')
                reader = PdfReader(path)
                self.assertEqual(len(reader.pages),len(counts))
                self.assertEqual(reader.pages[0].mediabox.width > reader.pages[0].mediabox.height,
                                 orientation=='landscape' or label=='单题一页')
                if 'grid_layout' in record:
                    self.assertEqual([row['questions'] for row in record['grid_page_checks']], counts)
                    with Pdf.open(path) as visual:
                        start = 0
                        for page, count in zip(visual.pages, counts):
                            embedded, = page.obj['/Resources']['/XObject'].values()
                            image = PdfImage(embedded).as_pil_image().convert('RGB')
                            image.thumbnail((240,240), Image.Resampling.NEAREST)
                            pixels = set(image.getdata())
                            self.assertEqual(pixels & set(colors), set(colors[start:start+count]))
                            self.assertFalse(any(max(color)<70 for color in pixels))
                            start += count
                if combined:
                    quiz = lesson[field_for(dict(quiz_answers=True,quiz_layout=spec))]
                    self.assertEqual(quiz['grid_layout'], spec)
                    self.assertEqual(quiz['pages'],1)
                    self.assertEqual(quiz['annotated_pages'],1)
                else:
                    self.assertFalse(any(key.startswith('quiz_pdf') for key in lesson))
                return path

            original = export('portrait','单题一页',[1]*7)
            self.assertTrue(original.name.endswith('_课件.pdf'))
            original_bytes = original.read_bytes()
            for orientation in ('portrait','landscape'):
                for label, counts in [('每页2张',[2,2,2,1]),('每页4张',[4,3]),('每页6张',[6,1]),
                                      ('每页8张',[7]),('每页12张',[7])]:
                    with self.subTest(orientation=orientation,label=label):
                        path = export(orientation,label,counts)
                        self.assertIn('张每页',path.name)
            first = export('portrait','每页4张',[4,3])
            mtime = first.stat().st_mtime_ns
            self.assertEqual(first, export('portrait','每页4张',[4,3]))
            self.assertEqual(first.stat().st_mtime_ns,mtime)
            app.grid_rows.set('2')
            app.grid_columns.set('3')
            custom = export('portrait','自定义行列',[6,1])
            self.assertTrue(custom.name.endswith('_课件_竖版6张每页_2行3列.pdf'))
            export('landscape','每页8张',[7],combined=True)
            self.assertEqual(original.read_bytes(),original_bytes)
            self.assertFalse(unfinished(output,OWNER,ORIGIN,layout='flat',features=['courseware_pdf'],
                                        quiz_layout=app._grid_request()))
