"""Real serial worker with local site fixtures; independent grid task/cache keys."""
import gc
import tkinter as tk
import unittest
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from pypdf import PdfReader
import test_answer_workflow as fixtures
from ykt.answer_images import read_native_answer
from ykt.files import Manifest
from ykt.gui import CourseApp
from ykt.quiz_grid import normalize_layout,field_for,layout_suffix
from ykt.quiz_pdf import verified_pdf
from ykt.recovery import unfinished


class GridWorkerTests(unittest.TestCase):
    def setUp(self):
        self.flow=fixtures.AnswerWorkflowTests();self.flow.setUp()
    def tearDown(self):self.flow.tearDown()

    def test_pdf_only_grid_repeat_and_switch_configuration(self):
        a=normalize_layout(dict(count=2));b=normalize_layout(dict(count=4,orientation='landscape'))
        result,m,lesson=self.flow.run_job(True,images=False,grid=a)
        field_a=field_for(dict(quiz_answers=True,quiz_layout=a));pdf=lesson[field_a]
        self.assertEqual(result['success'],1);self.assertEqual(pdf['pages'],1)
        self.assertEqual(pdf['question_count'],2)
        self.assertTrue(verified_pdf(m,pdf,answers=True,grid=a))
        old=m.resolve(pdf['path']);before=(old.read_bytes(),old.stat().st_mtime_ns)
        self.flow.run_job(True,images=False,no_fetch=True,grid=a)
        _,m,lesson=self.flow.run_job(True,images=False,grid=b)
        field_b=field_for(dict(quiz_answers=True,quiz_layout=b))
        self.assertIn(field_a,lesson);self.assertIn(field_b,lesson)
        self.assertNotEqual(lesson[field_a]['path'],lesson[field_b]['path'])
        self.assertEqual((old.read_bytes(),old.stat().st_mtime_ns),before)
        self.assertFalse(list((self.flow.root/'output').rglob('习题图片')))
        self.assertFalse(unfinished(self.flow.root/'output',fixtures.OWNER,fixtures.ORIGIN,layout='flat',
            features=['quiz_pdf'],quiz_answers=True,quiz_layout=b))

    def test_naming_prefix_stays_first_and_raw_images_keep_existing_names(self):
        self.flow.task['lesson']['created_at']=1792080000000
        spec=normalize_layout(dict(count=6))
        _,m,lesson=self.flow.run_job(True,mode='date',grid=spec)
        pdf=lesson[field_for(dict(quiz_answers=True,quiz_layout=spec))]
        self.assertEqual(m.resolve(pdf['path']).name,'1016_习题_习题合集_带答案_竖版6题每页.pdf')
        for record in lesson['resources'].values():
            self.assertTrue(m.resolve(record['path']).name.startswith('1016_习题_'))
            self.assertNotIn('题每页',record['path'])

    def test_gui_controls_start_pdf_and_deliver_selected_grid_to_writer(self):
        """Click the normal Start button. Only website and download I/O are fixtures."""
        project = self.flow.root / 'project'
        (project / '.local/changjiang.yuketang.cn').mkdir(parents=True)
        output = self.flow.root / 'gui-output'
        output.mkdir()
        task = self.flow.task
        task['lesson']['created_at'] = 1792080000000

        @contextmanager
        def browser(*args):
            yield None, fixtures.Page()

        def extract(*args, answers=False):
            items = []
            for i in range(14):
                item = dict(candidates=['https://local.invalid/same-image'], slide_id=str(i+10), page=i+1)
                if answers:
                    item['native_answer'] = read_native_answer('正确答案：AB' if i == 0 else '')
                items.append(item)
            return dict(resources=items, pages=14, unsupported=[])

        window = tk.Tk()
        window.withdraw()
        app = None
        try:
            app = CourseApp(window, project)
            app.worker.expected_owner = fixtures.OWNER
            app.worker.stop_event = fixtures.LocalStop()
            app.catalog = dict(owner_fingerprint=fixtures.OWNER,
                               courses=[dict(id='1', name=task['course_name'], class_name='2026秋-测试班',
                                             status='complete', lessons=[task['lesson']])])
            app.selection.replace(app.catalog)
            app._render_tree()
            app.toggle(app.term_iid('2026秋'))
            app.save_dir.set(str(output))
            app.export_images.set(False)
            cases = [(orientation, count) for orientation in ('portrait', 'landscape') for count in (2,4,6,8,12)]
            cases += [('portrait', 9), ('landscape', 9), ('portrait', 1)]
            with ExitStack() as stack:
                stack.enter_context(patch('ykt.worker.open_browser', side_effect=browser))
                for module in ('downloader', 'quiz_export'):
                    stack.enter_context(patch('ykt.'+module+'.verify_account'))
                stack.enter_context(patch('ykt.downloader.extract_lesson', side_effect=extract))
                stack.enter_context(patch('ykt.downloader._fetch', return_value=self.flow.jpeg))
                for index, (orientation,count) in enumerate(cases):
                    with self.subTest(orientation=orientation,count=count):
                        mode = ('original','date','sequence')[index%3]
                        app.naming_mode.set(mode)
                        app.export_quiz_pdf.set(False)
                        app._update_controls()
                        app.paper_radios[orientation == 'landscape'].invoke()
                        self.assertTrue(app.export_quiz_pdf.get())
                        app.export_quiz_pdf.set(False)
                        app.grid_box.set('自定义行列' if count == 9 else '单题一页' if count == 1 else f'每页{count}张')
                        app.grid_rows.set('3')
                        app.grid_columns.set('3')
                        app.grid_box.event_generate('<<ComboboxSelected>>')
                        self.assertTrue(app.export_quiz_pdf.get())
                        answers = index%2 == 0 and count != 1
                        app.export_answers.set(answers)
                        app.download_button.invoke()
                        self.assertIsNotNone(app.worker.thread, app.status.get())
                        app.worker.thread.join(40)
                        self.assertFalse(app.worker.running)
                        events = []
                        while not app.worker.events.empty():
                            events.append(app.worker.events.get_nowait())
                        results = [data for kind,data in events if kind == 'download_result']
                        self.assertEqual([r['success'] for r in results],[1],events)
                        manifest = Manifest(output, fixtures.OWNER, fixtures.ORIGIN, layout='flat')
                        spec = normalize_layout(dict(orientation=orientation, mode='custom' if count == 9 else 'preset',
                                                     rows=3, columns=3, count=count))
                        field = field_for(dict(quiz_answers=answers,quiz_layout=spec))
                        lesson = next(x for x in manifest.read_existing()['lessons'].values() if field in x)
                        pdf = lesson[field]
                        path = manifest.resolve(pdf['path'])
                        self.assertEqual(path.parent, output.resolve() / task['course_name'])
                        self.assertTrue(path.name.endswith(layout_suffix(spec)+'.pdf'))
                        self.assertEqual([count]* (14//count) + ([14%count] if 14%count else []),
                                         [row['questions'] for row in pdf['grid_page_checks']])
                        reader = PdfReader(path)
                        self.assertEqual(len(reader.pages),(14+count-1)//count)
                        self.assertEqual(reader.pages[0].mediabox.width > reader.pages[0].mediabox.height,
                                         orientation == 'landscape')
                        self.assertTrue(verified_pdf(manifest,pdf,answers=answers,grid=spec))
                        if answers:
                            self.assertEqual(pdf['annotated_pages'],1)
                            first_page = reader.pages[0].images[0].image.convert('RGB')
                            # The fixture question is entirely white, so dark
                            # pixels here verify the answer survived composition.
                            dark = first_page.convert('L').point(lambda level: 255 if level<70 else 0)
                            self.assertIsNotNone(dark.getbbox())
        finally:
            window.destroy()
            del app, window
            gc.collect()


if __name__=='__main__':unittest.main()
