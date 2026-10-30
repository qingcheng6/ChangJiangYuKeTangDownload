"""Real serial worker with local site fixtures; independent grid task/cache keys."""
import unittest
import test_answer_workflow as fixtures
from ykt.quiz_grid import normalize_layout,field_for
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


if __name__=='__main__':unittest.main()
