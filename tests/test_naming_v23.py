"""Local naming/real-worker tests; site boundaries use labeled local fixtures."""
import io
import tempfile
import time
import tkinter as tk
import unittest
from contextlib import contextmanager, ExitStack
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from unittest.mock import patch

from PIL import Image
from ykt.files import FileProblem, Manifest, safe_prefixed_name, units
from ykt.gui import CourseApp
from ykt.naming import (NamingControl, NamingPlan, chinese_number, date_prefix,
                        lesson_key, prepare_positions, snapshot)
from ykt.quiz_pdf import pdf_path
from ykt.recovery import unfinished
from ykt.storage import read_json, write_json
from ykt.worker import ScanWorker

ORIGIN = 'https://changjiang.yuketang.cn'
OWNER = 'a' * 64


class LocalStop(Event):
    def wait(self, timeout=None):
        return self.is_set()


class Page:
    def is_closed(self):
        return False


class NamingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ykt_naming_')
        self.root = Path(self.temp.name).resolve()
        stamp = int(datetime(2026, 10, 15, 16, tzinfo=timezone.utc).timestamp() * 1000)
        self.tasks = [dict(course_id='1', course_name='课程', lesson=dict(id=str(2+i*2),
                      courseware_id=str(3+i*2), name='课时'+str(i+1), created_at=stamp+i*86400000, is_finished=True)) for i in range(3)]
        self.catalog = dict(courses=[dict(id='1', lessons=[self.tasks[0]['lesson'],
                            dict(id='bad', courseware_id='0'), self.tasks[1]['lesson'], self.tasks[2]['lesson']])])
        buffer = io.BytesIO()
        Image.new('RGB', (64, 48), 'navy').save(buffer, 'JPEG')
        self.jpeg = buffer.getvalue()
        self.logs = []

    def tearDown(self):
        self.temp.cleanup()

    def boundaries(self, fetch=None):
        stack = ExitStack()
        @contextmanager
        def browser(*args):
            yield None, Page()
        def resources(_, __, task, *args):
            return [dict(candidates=['https://local.invalid/'+task['lesson']['id']],
                         slide_id=task['lesson']['id'], page=1)]
        self.browser_mock=stack.enter_context(patch('ykt.worker.open_browser', side_effect=browser))
        for module in ('downloader', 'quiz_export', 'resource_export'):
            stack.enter_context(patch('ykt.'+module+'.verify_account'))
        stack.enter_context(patch('ykt.downloader.extract_lesson', side_effect=lambda *args:
            dict(resources=resources(*args), pages=1, unsupported=[])))
        stack.enter_context(patch('ykt.courseware.extract_courseware', side_effect=resources))
        stack.enter_context(patch('ykt.downloader._fetch', side_effect=fetch or (lambda *args:self.jpeg)))
        stack.enter_context(patch('ykt.courseware._fetch', return_value=self.jpeg))
        return stack

    def run_worker(self, mode, tasks=None, hook=None, bits=7, output=None):
        output = output or self.root/'output'
        worker = ScanWorker(ORIGIN, self.root/'site', account_id='local-test', expected_owner=OWNER, layout='flat')
        worker.stop_event = LocalStop()
        worker.set_naming_mode(mode)
        original = worker._lesson_done
        def done(task, lesson):
            original(task, lesson)
            if hook:
                hook(worker, task, lesson)
        worker._lesson_done = done
        with self.boundaries():
            worker.start_download(deepcopy(tasks or self.tasks[:1]), output, OWNER,
                dict(quiz_images=bool(bits&1), quiz_pdf=bool(bits&2), courseware_pdf=bool(bits&4)), catalog=self.catalog)
            worker.thread.join(10)
            self.assertFalse(worker.running)
            self.assertEqual(self.browser_mock.call_count,1)
        events = []
        while not worker.events.empty():
            events.append(worker.events.get())
        self.assertFalse([x for x in events if x[0] in ('error','needs_human')], events)
        self.logs.extend(value for kind,value in events if kind=='log')
        result = next(value for kind,value in events if kind=='download_result')
        return result, Manifest(output, OWNER, ORIGIN, layout='flat').read_existing()

    def test_date_timezone_invalid_date_and_chinese_numbers(self):
        self.assertEqual(date_prefix(self.tasks[0]['lesson']['created_at']), '1016_')
        for invalid in (None, '', True, -1, float('inf'), float('nan')):
            self.assertEqual(date_prefix(invalid), '')
        expected = {1:'一', 10:'十', 11:'十一', 20:'二十', 101:'一百零一', 110:'一百一十',
                    1001:'一千零一', 10000:'一万', 10001:'一万零一', 100000001:'一亿零一'}
        for value, text in expected.items():
            self.assertEqual(chinese_number(value), text)

    def test_full_course_order_not_selected_subset_or_date_sort(self):
        tasks = deepcopy([self.tasks[2]])
        prepare_positions(tasks, self.catalog)
        self.assertEqual(snapshot(tasks[0], 'sequence')['prefix'], '（三）')
        self.assertEqual(tasks[0]['_course_position'], 3)
        other = dict(id='9', lessons=[self.tasks[1]['lesson']])
        catalog = dict(courses=self.catalog['courses']+[other])
        selected = [dict(self.tasks[1], course_id='9')]
        prepare_positions(selected, catalog)
        self.assertEqual(snapshot(selected[0], 'sequence')['prefix'], '（一）')

    def test_invalid_selected_record_is_skipped_without_consuming_position(self):
        invalid=dict(self.tasks[0],lesson=dict(id='bad',name='失效课时'))
        result,data=self.run_worker('sequence',[invalid,dict(self.tasks[0],lesson=None),self.tasks[1]])
        self.assertEqual(result['total'],1)
        self.assertEqual(result['success'],1)
        self.assertTrue((self.root/'output/课程/（二）课时2_课件.pdf').exists())
        self.assertTrue(any('失效记录' in line for line in self.logs))

    def test_all_modes_same_course_independent_resume_and_identical_pdf_bytes(self):
        output = self.root/'output'
        snapshots = {}
        for mode, prefix in (('original',''), ('date','1016_'), ('sequence','（一）')):
            result, data = self.run_worker(mode)
            self.assertEqual(result['success'], 1)
            self.assertEqual(data['courses'], {'1':'课程'})
            expected = ['课程/'+prefix+'课时1_课件.pdf', '课程/'+prefix+'课时1_习题合集.pdf',
                        '课程/习题图片/'+prefix+'课时1/'+prefix+'习题_001.jpg']
            snapshots[mode] = {name:((output/name).read_bytes(), (output/name).stat().st_mtime_ns) for name in expected}
            self.assertEqual(self.run_worker(mode)[0]['downloaded'], 0)
            for saved in snapshots.values():
                for name, before in saved.items():
                    self.assertEqual(((output/name).read_bytes(),(output/name).stat().st_mtime_ns),before)
        self.assertEqual(len(data['lessons']), 3)
        self.assertEqual(snapshots['original']['课程/课时1_课件.pdf'][0], snapshots['date']['课程/1016_课时1_课件.pdf'][0])
        self.assertEqual(snapshots['original']['课程/课时1_习题合集.pdf'][0], snapshots['sequence']['课程/（一）课时1_习题合集.pdf'][0])

    def test_change_during_images_keeps_current_pdfs_and_changes_next_lesson(self):
        def change(worker, task, lesson):
            if task['lesson']['id']=='2' and lesson['status']=='complete':
                worker.set_naming_mode('date')
        result, data = self.run_worker('original', self.tasks[:2], change)
        self.assertEqual(result['success'], 2)
        files = {p.relative_to(self.root/'output').as_posix() for p in (self.root/'output').rglob('*') if p.suffix=='.pdf'}
        self.assertEqual(files, {'课程/课时1_习题合集.pdf','课程/课时1_课件.pdf',
                                 '课程/1017_课时2_习题合集.pdf','课程/1017_课时2_课件.pdf'})
        self.assertEqual(len(data['lessons']), 2)
        self.assertEqual(unfinished(self.root/'output', OWNER, ORIGIN, layout='flat', features=['quiz_pdf','courseware_pdf']), [])
        self.assertEqual(unfinished(self.root/'output', OWNER, ORIGIN, layout='flat', features=['quiz_pdf','courseware_pdf'],naming_mode='date'), [])

    def test_stop_after_switch_moves_only_new_unstarted_placeholders(self):
        def change_and_stop(worker, task, lesson):
            if task['lesson']['id']=='2' and lesson['status']=='complete':
                worker.set_naming_mode('sequence')
                worker.stop()
        result, data = self.run_worker('original', self.tasks[:2], change_and_stop)
        self.assertEqual(result['status'],'stopped')
        original = unfinished(self.root/'output',OWNER,ORIGIN,layout='flat',features=['quiz_pdf','courseware_pdf'])
        sequence = unfinished(self.root/'output',OWNER,ORIGIN,layout='flat',features=['quiz_pdf','courseware_pdf'],naming_mode='sequence')
        self.assertEqual([x['lesson_id'] for x in original],['2'])
        self.assertEqual([x['lesson_id'] for x in sequence],['4'])
        self.assertEqual(self.run_worker('sequence',[self.tasks[1]])[0]['success'],1)
        # Stop immediately after binding, before the feature opens its manifest.
        # The new mode still needs an unfinished entry, not a stale old-mode row.
        from ykt.quiz_export import _record_pending_pdfs
        tasks=deepcopy(self.tasks[:2]);prepare_positions(tasks,self.catalog)
        control=NamingControl();plan=NamingPlan(control,tasks)
        request=dict(tasks=tasks,directory=self.root/'before_feature',owner=OWNER,naming=plan,
                     options=dict(quiz_images=False,quiz_pdf=True,courseware_pdf=True))
        _record_pending_pdfs(request,ORIGIN,'flat',['quiz_pdf','courseware_pdf'])
        control.set('date');plan.bind(tasks[0],self.logs.append)
        plan.finish_pending(request,ORIGIN,'flat')
        self.assertEqual(len(unfinished(request['directory'],OWNER,ORIGIN,layout='flat',features=['quiz_pdf'])),0)
        self.assertEqual(len(unfinished(request['directory'],OWNER,ORIGIN,layout='flat',features=['quiz_pdf'],naming_mode='date')),2)

    def test_pdf_only_and_missing_date_fallback_are_independent(self):
        task = deepcopy(self.tasks[0]); task['lesson']['created_at']=None
        result, data = self.run_worker('date',[task],bits=6)
        self.assertEqual(result['success'],1)
        self.assertTrue((self.root/'output/课程/课时1_课件.pdf').exists())
        self.assertFalse(list((self.root/'output').rglob('习题图片')))
        self.assertTrue(any('回退原命名' in line for line in self.logs))
        self.assertEqual(len(data['lessons']),1)
        self.assertEqual(next(iter(data['lessons'].values()))['naming']['mode'],'date')
        self.run_worker('original',[task],bits=6)
        self.assertEqual(len(list((self.root/'output').rglob('*.pdf'))),4)

    def test_valid_prefixed_pdf_only_and_corrupt_mode_does_not_touch_other_mode(self):
        result, data=self.run_worker('date',bits=6)
        self.assertEqual(result['success'],1)
        output=self.root/'output'
        self.assertTrue((output/'课程/1016_课时1_习题合集.pdf').exists())
        self.assertFalse(list(output.rglob('习题图片')))
        self.run_worker('original',bits=6)
        original=output/'课程/课时1_课件.pdf';old=(original.read_bytes(),original.stat().st_mtime_ns)
        damaged=output/'课程/1016_课时1_课件.pdf';expected=damaged.read_bytes();damaged.write_bytes(expected[:10])
        self.run_worker('date',bits=6)
        self.assertEqual(damaged.read_bytes(),expected)
        self.assertEqual((original.read_bytes(),original.stat().st_mtime_ns),old)

    def test_all_future_pdf_suffixes_prefix_and_windows_names(self):
        for mode in ('original','date','sequence'):
            task = deepcopy(self.tasks[0]);task['lesson']['name']='CON'
            prepare_positions([task],self.catalog);task['_naming']=snapshot(task,mode)
            with Manifest(self.root/mode,OWNER,ORIGIN,layout='flat') as m:
                lesson=m.lesson(task)
                for suffix in ('_课件.pdf','_习题合集_带答案.pdf','_习题合集_6题每页.pdf','_习题合集_带答案_6题每页.pdf'):
                    path=pdf_path(m,task,lesson,{},suffix)
                    self.assertTrue(path.name.startswith(task['_naming']['prefix']+'_CON'))
                    self.assertTrue(path.name.endswith(suffix))
                    self.assertLessEqual(units(path),240)
        self.assertTrue(safe_prefixed_name('很长'*100,'1016_',14).startswith('1016_'))

    def test_malformed_naming_record_is_preserved_and_rejected(self):
        self.run_worker('date')
        manifest=Manifest(self.root/'output',OWNER,ORIGIN,layout='flat')
        data=manifest.read_existing()
        next(iter(data['lessons'].values()))['naming']=[]
        write_json(manifest.path,data)
        before=manifest.path.read_bytes()
        with self.assertRaises(FileProblem):manifest.read_existing()
        self.assertEqual(manifest.path.read_bytes(),before)

    def test_preferences_and_radio_buttons_keep_old_directory_settings(self):
        project=self.root/'project';(project/'.local/changjiang.yuketang.cn').mkdir(parents=True)
        settings=project/'.local/gui_settings.json';write_json(settings,dict(schema_version=1,save_directory=str(self.root)))
        old=settings.read_bytes();window=tk.Tk();window.withdraw()
        try:
            app=CourseApp(window,project)
            self.assertEqual(app.naming_mode.get(),'original')
            app.naming_radios[1].invoke()
            self.assertEqual(app.worker.naming_control.get(),'date')
            self.assertEqual(read_json(project/'.local/naming_settings.json')['mode'],'date')
            self.assertEqual(settings.read_bytes(),old)
            other=app.accounts.add('另一个账号')
            with patch.object(app,'start_scan'):
                app.switch_account(other['id'])
            self.assertEqual(app.worker.naming_control.get(),'date')
            self.assertEqual(app.naming_mode.get(),'date')
            self.assertEqual(settings.read_bytes(),old)
            self.assertEqual(app.callback_errors,[])
        finally:window.destroy()
        window=tk.Tk();window.withdraw()
        try:
            app=CourseApp(window,project)
            self.assertEqual(app.naming_mode.get(),'date')
            self.assertEqual(app.worker.naming_control.get(),'date')
        finally:window.destroy()


if __name__=='__main__':
    unittest.main()
