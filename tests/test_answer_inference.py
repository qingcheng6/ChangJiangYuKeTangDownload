"""Local decision/evidence fixtures, separate from the live report acceptance."""
import copy
import unittest
from unittest.mock import Mock

from playwright.sync_api import Error
from ykt.answer_images import (select_answer,full_score,infer_submission,
    trusted_answer,annotated_sources,ANNOTATION_VERSION)
from ykt.extractor import answer_for_item
from ykt.files import FileProblem


def evidence(**changes):
    row=dict(result_text='AB',submitted='AB',classes=['pr12','green'],
             color='rgb(8, 188, 114)',visible=True,score='2/2')
    row.update(changes)
    return row


class AnswerInferenceTests(unittest.TestCase):
    def test_official_has_priority_without_reading_submitted_dom(self):
        for text in ('正确答案：C','参考答案：C'):
            self.assertEqual(select_answer(text,evidence())['answer'],'C')
        item=Mock();item.inner_text.return_value='正确答案：C'
        item.evaluate.side_effect=AssertionError('Official does not require result DOM')
        result=answer_for_item(item)
        self.assertEqual(result['confidence'],'official');item.evaluate.assert_not_called()

    def test_fallback_requires_both_green_and_full_score(self):
        result=select_answer('提交答案: AB 得分: 2/2',evidence())
        self.assertEqual(result['answer'],'AB')
        self.assertEqual(result['source'],'submission_verified')
        self.assertEqual(result['confidence'],'verified_submission')
        self.assertTrue(trusted_answer(result))
        for changes in (dict(score='1/2'),dict(score=None),dict(classes=['pr12','red']),
                dict(color='rgb(248, 79, 65)'),dict(color='rgb(0, 128, 0)'),
                dict(classes=['green','red']),dict(visible=False),dict(classes=None)):
            with self.subTest(changes=changes):
                result=infer_submission(evidence(**changes))
                self.assertEqual(result['status'],'missing');self.assertIsNone(result['answer'])
                self.assertEqual(result['reason_code'],'no_usable_correct_answer')

    def test_full_score_uses_exact_decimal_numbers_not_fraction_or_float_guessing(self):
        for value in ('1/1','10/10','2.50 / 2.5','0.10/0.1','１／１'):
            self.assertTrue(full_score(value),value)
        for value in (None,'','1','1/1/1','1/2','NaN/NaN','inf/inf','a/a','1e2/100',
                      '1/1 分','0/0','-1/-1','0.10000000000000001/0.1'):
            self.assertFalse(full_score(value),str(value))

    def test_green_status_only_or_disagreement_never_becomes_letters(self):
        for changes in (dict(result_text='全对',submitted=None),dict(submitted=''),
                        dict(result_text='A',submitted='B'),dict(submitted='TRUE',result_text='TRUE')):
            self.assertIsNone(infer_submission(evidence(**changes))['answer'])
        self.assertIsNone(select_answer('提交答案: A 得分: 1/1')['answer'])

    def test_empty_or_unrecognized_official_answer_allows_verified_fallback(self):
        for text in ('正确答案：','参考答案：暂不公布','提交答案: AB 得分: 2/2'):
            self.assertEqual(select_answer(text,evidence())['answer'],'AB')

    def test_single_question_dom_error_is_missing_next_question_still_succeeds(self):
        for exception in (Error('Local fixture error'),RuntimeError('Local fixture unexpected error')):
            broken=Mock();broken.inner_text.side_effect=exception
            result=answer_for_item(broken)
            self.assertEqual(result['status'],'missing')
            self.assertEqual(result['reason_code'],'no_usable_correct_answer')
        good=Mock();good.inner_text.return_value='提交答案: AB 得分: 2/2'
        good.evaluate.return_value=evidence()
        self.assertEqual(answer_for_item(good)['answer'],'AB')

    def test_fallback_evidence_is_bound_into_mapping_and_revalidated(self):
        sequence=[dict(resource_id='r',slide_id='s',page=1)]
        mapping=dict(sequence[0],occurrence=0,**infer_submission(evidence()))
        paths,identity,stats=annotated_sources(['not-read-here'],sequence,[mapping])
        self.assertEqual(stats['annotated_pages'],1)
        self.assertTrue(trusted_answer(identity[0]))
        self.assertEqual(identity[0]['evidence'],evidence())
        for changes in (dict(score='1/2'),dict(color='rgb(248, 79, 65)')):
            tampered=copy.deepcopy(mapping);tampered['evidence'].update(changes)
            self.assertFalse(trusted_answer(tampered))
            with self.assertRaises(FileProblem):annotated_sources(['unused'],sequence,[tampered])
        self.assertGreater(ANNOTATION_VERSION,1)


if __name__=='__main__':unittest.main()
