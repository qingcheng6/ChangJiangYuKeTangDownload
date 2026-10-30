"""Actual worker/GUI with labeled local site fixtures; not live-positive proof."""
import io
import gc
import tempfile
import tkinter as tk
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from threading import Event
from unittest.mock import patch

from PIL import Image
from ykt.answer_images import read_native_answer
from ykt.files import Manifest
from ykt.gui import CourseApp
from ykt.recovery import unfinished
from ykt.worker import ScanWorker

ORIGIN='https://changjiang.yuketang.cn'
OWNER='a'*64


class LocalStop(Event):
    def wait(self, timeout=None):return self.is_set()


class Page:
    def is_closed(self):return False


class AnswerWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='native_answer_flow_');self.root=Path(self.temp.name)
        self.task=dict(course_id='1',course_name='课程',lesson=dict(id='2',courseware_id='3',name='习题'))
        buffer=io.BytesIO();Image.new('RGB',(640,480),'white').save(buffer,'JPEG');self.jpeg=buffer.getvalue()
        self.logs=[]

    def tearDown(self):self.temp.cleanup()

    def run_job(self,marked,images=True,positive=True,no_fetch=False,mode='original'):
        @contextmanager
        def browser(*args):yield None,Page()
        def extract(*args,answers=False):
            rows=[]
            for i in range(2):
                row=dict(candidates=['https://local.invalid/same-image'],slide_id=str(i+10),page=i+1)
                if answers:
                    text='正确答案：AB' if i==0 and positive else '提交答案: D 得分: 1/1'
                    row['native_answer']=read_native_answer(text)
                rows.append(row)
            return dict(resources=rows,pages=2,unsupported=[])
        worker=ScanWorker(ORIGIN,self.root/'site',account_id='test',expected_owner=OWNER,layout='flat')
        worker.set_naming_mode(mode)
        worker.stop_event=LocalStop()
        with ExitStack() as stack:
            stack.enter_context(patch('ykt.worker.open_browser',side_effect=browser))
            for module in ('downloader','quiz_export','resource_export'):
                stack.enter_context(patch('ykt.'+module+'.verify_account'))
            stack.enter_context(patch('ykt.downloader.extract_lesson',side_effect=extract))
            stack.enter_context(patch('ykt.downloader._fetch',side_effect=AssertionError('Must skip') if no_fetch else lambda *args:self.jpeg))
            worker.start_download([self.task],self.root/'output',OWNER,
                dict(quiz_images=images,quiz_pdf=True,courseware_pdf=False,quiz_answers=marked),
                catalog=dict(courses=[dict(id='1',lessons=[self.task['lesson']])]))
            worker.thread.join(10);self.assertFalse(worker.running)
        events=[]
        while not worker.events.empty():events.append(worker.events.get())
        self.assertFalse([e for e in events if e[0] in ('error','needs_human')],events)
        self.logs.extend(v for k,v in events if k=='log')
        result=next(v for k,v in events if k=='download_result')
        m=Manifest(self.root/'output',OWNER,ORIGIN,layout='flat')
        rows=m.read_existing()['lessons'].values()
        return result,m,next(row for row in rows if row.get('naming',{}).get('mode','original')==mode)

    def test_marked_suffix_follows_all_naming_prefixes_without_changing_course_name(self):
        self.task['lesson']['created_at']=1792080000000
        seen=set()
        for mode,prefix in [('original',''),('date','1016_'),('sequence','（一）')]:
            _,manifest,lesson=self.run_job(True,mode=mode)
            path=manifest.resolve(lesson['quiz_pdf_answers']['path'])
            self.assertEqual(path.parent.name,'课程')
            self.assertEqual(path.name,prefix+'习题_习题合集_带答案.pdf')
            seen.add(path)
            for record in lesson['resources'].values():
                image=manifest.resolve(record['path'])
                self.assertEqual(image.parent.name,prefix+'习题')
                self.assertTrue(image.name.startswith(prefix+'习题_'))
        self.assertEqual(len(seen),3)

    def test_original_images_plain_pdf_and_marked_pdf_coexist(self):
        self.run_job(False)
        output=self.root/'output'
        before={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in output.rglob('*') if p.suffix in ('.jpg','.pdf')}
        result,m,lesson=self.run_job(True)
        self.assertEqual(result['downloaded'],0)
        self.assertEqual(lesson['quiz_pdf']['status'],'complete')
        self.assertEqual(lesson['quiz_pdf_answers']['annotated_pages'],1)
        self.assertEqual(lesson['quiz_pdf_answers']['missing_answers'],1)
        for p,value in before.items():self.assertEqual((p.read_bytes(),p.stat().st_mtime_ns),value)
        self.assertFalse(unfinished(output,OWNER,ORIGIN,layout='flat',features=['quiz_pdf'],quiz_answers=True))

    def test_pdf_only_uses_memory_labels_and_repeated_completed_variant_skips(self):
        result,m,lesson=self.run_job(True,images=False)
        self.assertEqual(result['success'],1)
        self.assertTrue(lesson['quiz_pdf_answers']['path'].endswith('_习题合集_带答案.pdf'))
        self.assertFalse(list((self.root/'output').rglob('习题图片')))
        self.assertEqual(self.run_job(True,images=False,no_fetch=True)[0]['downloaded'],0)

    def test_submitted_answer_is_not_promoted_to_standard_answer(self):
        self.run_job(False,positive=False)
        result,m,lesson=self.run_job(True,positive=False)
        self.assertEqual(result['success'],1)
        self.assertEqual(lesson['quiz_pdf_answers']['annotated_pages'],0)
        self.assertEqual(lesson['quiz_pdf_answers']['missing_answers'],2)
        self.assertEqual(m.resolve(lesson['quiz_pdf']['path']).read_bytes(),
                         m.resolve(lesson['quiz_pdf_answers']['path']).read_bytes())
        self.assertTrue(any('无答案' in line for line in self.logs))

    def test_gui_modifier_defaults_off_enables_pdf_and_clears_when_pdf_disabled(self):
        project=self.root/'project';project.mkdir()
        window=tk.Tk();window.withdraw()
        try:
            app=CourseApp(window,project)
            self.assertFalse(app.export_answers.get())
            app.answer_check.invoke()
            self.assertTrue(app.export_answers.get());self.assertTrue(app.export_quiz_pdf.get())
            app.answer_check.invoke()
            self.assertFalse(app.export_answers.get());self.assertTrue(app.export_quiz_pdf.get())
            app.answer_check.invoke();app.export_quiz_pdf.set(False);app._update_controls()
            self.assertFalse(app.export_answers.get())
            self.assertEqual(app.callback_errors,[])
        finally:
            window.destroy()
            del app,window
            gc.collect()  # Tk objects must be finalized on the test's main thread.


if __name__=='__main__':unittest.main()
