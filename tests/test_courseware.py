"""Local fault tests; mocked extraction is not a live website acceptance claim."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch
from pypdf import PdfReader
from ykt.browser import PageChanged, Stopped
from ykt.courseware import (LANDSCAPE, PURPOSE, export_courseware,
                            ordered_slides, verified_courseware)
from ykt.files import Manifest
from ykt.pdf_work import PdfWork
from ykt.recovery import unfinished
from ykt.resource_export import export_resources

ROOT=Path(__file__).resolve().parents[1]
ORIGIN='https://changjiang.yuketang.cn'


class CoursewareTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='courseware_test_',dir=ROOT/'.local')
        self.root=Path(self.temp.name).resolve()
        self.owner='b'*64
        self.task=dict(course_id='1',course_name='local test',lesson=dict(id='2',courseware_id='3',name='static lesson'))
        self.stop=Event()
        self.jpeg=[p.read_bytes() for p in sorted((ROOT/'.local/phase3_output').rglob('习题_*.jpg'))[:2]]
        self.assertEqual(len(self.jpeg),2)
        self.resources=[dict(candidates=['https://local.invalid/image'+str(i)],slide_id=str(i+10),page=i+1) for i in range(2)]
        self.log=[]
        self.work=PdfWork(self.root,'account',self.task,self.owner,ORIGIN,purpose=PURPOSE)

    def tearDown(self):
        # Only the exact owned test cache; failed jobs intentionally retain it.
        if self.work.root.exists():
            with self.work as work:work.discard=True
        self.assertIn((ROOT/'.local').resolve(),self.root.parents)
        self.temp.cleanup()

    def run_export(self,resources=None,fetch=None,emit=None):
        resources=self.resources if resources is None else resources
        def get(_,resource,*args):return self.jpeg[int(resource['page'])-1]
        with patch('ykt.courseware.extract_courseware',return_value=resources),patch('ykt.courseware._fetch',side_effect=fetch or get) as call:
            result=export_courseware(None,None,ORIGIN,self.task,self.root/'out',self.owner,self.root,'account','v2',self.stop,emit or self.log.append)
        return result,call

    def manifest(self):return Manifest(self.root/'out',self.owner,ORIGIN,layout='v2')

    def test_original_page_order_hidden_records_and_ambiguous_pages(self):
        def row(i,page,**extra):return dict(slide_id=str(i),page=page,visible=True,kind='slide',**extra)
        slides=[row(13,13),row(11,11),row(11,11),dict(row(35,35),visible=False),row(12,12)]
        self.assertEqual([s['page'] for _,s in ordered_slides(slides)],[11,12,13])
        with self.assertRaises(PageChanged):ordered_slides([row(1,1),row(2,1)])
        with self.assertRaises(PageChanged):ordered_slides([row(1,1,cover='https://local.invalid/a'),row(1,1,cover='https://local.invalid/b')])
        with self.assertRaises(PageChanged):ordered_slides([dict(row(1,1),kind='video')])

    def test_landscape_full_count_original_bytes_and_repeat(self):
        result,call=self.run_export()
        self.assertEqual(result['status'],'complete');self.assertEqual(call.call_count,2)
        m=self.manifest();path=m.resolve(result['path']);self.assertTrue(verified_courseware(m,result,self.stop))
        pdf=PdfReader(path)
        self.assertEqual(len(pdf.pages),2)
        for page,jpeg in zip(pdf.pages,self.jpeg):
            self.assertAlmostEqual(float(page.mediabox.width),LANDSCAPE[0],places=2)
            self.assertEqual(page['/Resources']['/XObject']['/Im0'].get_object().get_data(),jpeg)
        before=path.stat().st_mtime_ns
        repeated,call=self.run_export();self.assertTrue(repeated['skipped']);self.assertEqual(call.call_count,0)
        self.assertEqual(path.stat().st_mtime_ns,before);self.assertFalse(self.work.root.exists())

    def test_corrupt_pdf_is_regenerated(self):
        result,_=self.run_export();path=self.manifest().resolve(result['path']);expected=hashlib.sha256(path.read_bytes()).hexdigest()
        path.write_bytes(path.read_bytes()[:100]);self.assertFalse(verified_courseware(self.manifest(),result,self.stop))
        result,call=self.run_export();self.assertEqual(result['status'],'complete');self.assertEqual(call.call_count,2)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),expected)

    def test_partial_image_failure_retries_and_resumes_verified_page(self):
        def fail(_,resource,*args):
            if resource['page']==2:raise OSError('local fault fixture')
            return self.jpeg[0]
        result,call=self.run_export(fetch=fail)
        self.assertEqual(result['status'],'failed');self.assertEqual(call.call_count,4)
        self.assertFalse(list((self.root/'out').rglob('*.pdf')))
        self.assertEqual(len(unfinished(self.root/'out',self.owner,ORIGIN,layout='v2',features=['courseware_pdf'])),1)
        result,call=self.run_export();self.assertEqual(result['status'],'complete');self.assertEqual(call.call_count,1)
        self.assertFalse(unfinished(self.root/'out',self.owner,ORIGIN,layout='v2',features=['courseware_pdf']))

    def test_pdf_write_failure_keeps_old_file_and_independent_quiz_state(self):
        result,_=self.run_export();m=self.manifest();path=m.resolve(result['path']);before=path.read_bytes()
        with m as manifest:
            lesson=manifest.lesson(self.task);lesson['courseware_pdf']['fingerprint']='changed';lesson['status']='complete'
            lesson['quiz_pdf']=dict(status='complete',sha256='a'*64);manifest.save()
        with patch('ykt.courseware.write_pdf',side_effect=OSError('local write fault')) as write:
            result,_=self.run_export()
        self.assertEqual(result['status'],'failed');self.assertEqual(write.call_count,3);self.assertEqual(path.read_bytes(),before)
        lesson=next(iter(m.read_existing()['lessons'].values()));self.assertEqual(lesson['status'],'complete');self.assertEqual(lesson['quiz_pdf']['status'],'complete')
        self.assertFalse(list(m.root.rglob('*.part')))

    def test_stop_preserves_verified_cache_then_resumes(self):
        def stop(message):
            if message.startswith('已读取课件页 1/'):self.stop.set()
        with self.assertRaises(Stopped):self.run_export(emit=stop)
        self.assertTrue(self.work.root.exists());self.assertFalse(list((self.root/'out').rglob('*.pdf')))
        self.stop.clear();result,call=self.run_export();self.assertEqual(result['status'],'complete');self.assertEqual(call.call_count,1)
        self.assertFalse(self.work.root.exists())

    def test_no_accessible_static_pages_no_empty_lesson_or_pdf(self):
        result,call=self.run_export(resources=[])
        self.assertEqual(result['status'],'no_images');self.assertEqual(call.call_count,0)
        m=self.manifest();lesson=next(iter(m.read_existing()['lessons'].values()))
        self.assertIsNone(lesson['directory']);self.assertFalse(list(m.root.rglob('*.pdf')))

    def test_error_lesson_does_not_stop_serial_queue(self):
        second=dict(self.task,lesson=dict(self.task['lesson'],id='4'))
        request=dict(tasks=[self.task,second],directory=self.root/'out',owner=self.owner,
                     options=dict(quiz_images=False,quiz_pdf=False,courseware_pdf=True))
        completed=[]
        with patch('ykt.resource_export.verify_account'),patch('ykt.resource_export.export_courseware',side_effect=[dict(status='failed'),dict(status='complete')]) as export:
            result=export_resources(None,None,ORIGIN,request,self.root,'account','v2',self.stop,self.log.append,
                                    lambda *_:None,lambda task,f,r:completed.append((task['lesson']['id'],f,r['status'])),lambda _:None)
        self.assertEqual(export.call_count,2);self.assertEqual(result['failed'],1);self.assertEqual(result['success'],1)
        self.assertEqual(completed,[('2','courseware_pdf','failed'),('4','courseware_pdf','complete')])

    def test_work_cache_is_separate_from_quiz_pdf(self):
        quiz=PdfWork(self.root,'account',self.task,self.owner,ORIGIN)
        self.assertNotEqual(quiz.root,self.work.root)

if __name__=='__main__':unittest.main()
