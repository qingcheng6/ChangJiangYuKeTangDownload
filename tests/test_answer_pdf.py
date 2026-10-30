"""Variant/resume tests with explicit local answer fixtures, not live answers."""
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from PIL import Image
from ykt.answer_images import ANSWER_FIELD
from ykt.browser import Stopped
from ykt.downloader import _atomic_image
from ykt.files import Manifest, image_info
from ykt.quiz_pdf import merge_lesson, verified_pdf

ORIGIN='https://changjiang.yuketang.cn'
OWNER='a'*64


class AnswerPdfTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='native_answer_pdf_')
        self.root=Path(self.temp.name)
        self.task=dict(course_id='1',course_name='课程',lesson=dict(id='2',courseware_id='3',name='习题'))
        buffer=io.BytesIO();Image.new('RGB',(640,480),'navy').save(buffer,'JPEG');self.jpeg=buffer.getvalue()
        self.source=Manifest(self.root/'source',OWNER,ORIGIN,layout='flat')
        with self.source as m:
            lesson=m.lesson(self.task);rid=hashlib.sha256(b'local image').hexdigest()
            record=dict(resource_id=rid,status='pending');lesson['resources'][rid]=record
            info=image_info(self.jpeg);path=m.output_path(self.task,lesson,record,info,1,rid)
            _atomic_image(m,path,record,self.jpeg,Event());record.update(info,status='complete')
            lesson.update(status='complete',warnings=[],quiz_pages=2,
                          pdf_sequence=[dict(resource_id=rid,slide_id=str(i+10),page=i+1) for i in range(2)])
            lesson['native_answers']=[dict(row,occurrence=i,answer=answer,source='correct_dom',
                                          status='available' if answer else 'missing')
                                      for i,(row,answer) in enumerate(zip(lesson['pdf_sequence'],('AB',None)))]
            m.save()
        self.lesson=self.source.read_existing()['lessons']['1:2:3']
        self.target=Manifest(self.root/'output',OWNER,ORIGIN,layout='flat')
        self.log=[]

    def tearDown(self):self.temp.cleanup()

    def merge(self,marked):
        with self.target as target:
            return merge_lesson(target,self.task,self.source,self.lesson,Event(),self.log.append,answers=marked)

    def test_plain_and_marked_are_independent_and_original_is_never_changed(self):
        original=self.source.resolve(next(iter(self.lesson['resources'].values()))['path'])
        raw=(original.read_bytes(),original.stat().st_mtime_ns)
        plain=self.merge(False);plain_path=self.target.resolve(plain['path'])
        before=(plain_path.read_bytes(),plain_path.stat().st_mtime_ns)
        marked=self.merge(True)
        self.assertTrue(marked['path'].endswith('_习题合集_带答案.pdf'))
        self.assertNotEqual(marked['path'],plain['path'])
        self.assertEqual(marked['annotated_pages'],1);self.assertEqual(marked['missing_answers'],1)
        self.assertTrue(verified_pdf(self.target,marked,answers=True))
        self.assertFalse(verified_pdf(self.target,marked))
        self.assertEqual((plain_path.read_bytes(),plain_path.stat().st_mtime_ns),before)
        self.assertEqual((original.read_bytes(),original.stat().st_mtime_ns),raw)
        self.assertTrue(any('无答案' in line for line in self.log))

    def test_repeated_marked_pdf_skips_and_corrupt_marked_pdf_recovers(self):
        marked=self.merge(True);path=self.target.resolve(marked['path']);before=path.read_bytes()
        with patch('ykt.answer_images.annotate_bytes',side_effect=AssertionError('Must not redraw complete PDF')):
            self.assertTrue(self.merge(True)['skipped'])
        path.write_bytes(before[:10]);self.assertFalse(verified_pdf(self.target,marked,answers=True))
        repaired=self.merge(True)
        self.assertEqual(repaired['status'],'complete');self.assertEqual(path.read_bytes(),before)
        self.assertFalse(list((self.root/'output').rglob('*.part')))

    def test_mapping_mismatch_keeps_valid_pdf_and_plain_status(self):
        self.merge(False);marked=self.merge(True);path=self.target.resolve(marked['path']);before=path.read_bytes()
        self.lesson['native_answers'][0]['slide_id']='wrong'
        failed=self.merge(True)
        self.assertEqual(failed['status'],'failed');self.assertEqual(path.read_bytes(),before)
        current=self.target.read_existing()['lessons']['1:2:3']
        self.assertEqual(current['quiz_pdf']['status'],'complete')
        self.assertEqual(current[ANSWER_FIELD]['status'],'failed')

    def test_partial_download_blocks_marked_pdf_and_does_not_affect_plain(self):
        plain=self.merge(False);original=self.target.resolve(plain['path']).read_bytes()
        self.lesson['status']='partial'
        self.assertEqual(self.merge(True)['status'],'failed')
        self.assertEqual(self.target.resolve(plain['path']).read_bytes(),original)
        self.assertFalse(list((self.root/'output').rglob('*_带答案.pdf')))

    def test_stopped_memory_render_keeps_valid_pdf_and_can_resume(self):
        marked=self.merge(True);path=self.target.resolve(marked['path']);before=path.read_bytes()
        self.lesson['native_answers'][0]['answer']='C'
        with patch('ykt.answer_images.annotate_bytes',side_effect=Stopped):
            with self.assertRaises(Stopped):self.merge(True)
        self.assertEqual(path.read_bytes(),before)
        self.assertFalse(list((self.root/'output').rglob('*.part')))
        resumed=self.merge(True)
        self.assertEqual(resumed['status'],'complete')
        self.assertNotEqual(path.read_bytes(),before)

    def test_transient_memory_render_failure_retries_without_intermediate_image(self):
        from ykt.answer_images import annotate_bytes
        calls=[]
        def flaky(data,answer):
            calls.append(answer)
            if len(calls)==1:raise OSError('Local render fixture failure')
            return annotate_bytes(data,answer)
        with patch('ykt.answer_images.annotate_bytes',side_effect=flaky), patch.object(Event,'wait',return_value=False):
            result=self.merge(True)
        self.assertEqual(result['status'],'complete');self.assertEqual(result['attempts_last_run'],2)
        self.assertEqual(len(calls),2)
        self.assertFalse(list((self.root/'output').rglob('*.png')))

    def test_no_images_creates_no_pdf_or_image_directory(self):
        self.lesson.update(status='no_images',quiz_pages=0)
        self.assertEqual(self.merge(True)['status'],'no_images')
        self.assertFalse(list((self.root/'output').rglob('*.pdf')))
        self.assertFalse(list((self.root/'output').rglob('习题图片')))


if __name__=='__main__':unittest.main()
