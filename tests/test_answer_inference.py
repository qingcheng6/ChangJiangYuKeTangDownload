"""Native-only policy regression, including explicit denial of legacy inference."""
import unittest
from unittest.mock import Mock

from playwright.sync_api import Error
from ykt.answer_images import (select_answer,
    trusted_answer,annotated_sources,ANNOTATION_VERSION)
from ykt.extractor import answer_for_item
from ykt.files import FileProblem


def evidence(**changes):
    row=dict(result_text='AB',submitted='AB',classes=['pr12','green'],
             color='rgb(8, 188, 114)',visible=True,score='2/2')
    row.update(changes)
    return row


class NativeOnlyTests(unittest.TestCase):
    def test_official_has_priority_without_reading_submitted_dom(self):
        for text in ('正确答案：C','参考答案：C'):
            self.assertEqual(select_answer(text,evidence())['answer'],'C')
        item=Mock();item.inner_text.return_value='正确答案：C'
        item.evaluate.side_effect=AssertionError('Official does not require result DOM')
        result=answer_for_item(item)
        self.assertEqual(result['confidence'],'official');item.evaluate.assert_not_called()

    def test_green_and_full_score_do_not_enable_fallback(self):
        result=select_answer('提交答案: AB 得分: 2/2',evidence())
        self.assertIsNone(result['answer'])
        self.assertEqual(result['source'],'none')
        self.assertEqual(result['confidence'],'none')
        self.assertFalse(trusted_answer(result))
        for changes in (dict(score='1/2'),dict(score=None),dict(classes=['pr12','red']),
                dict(color='rgb(248, 79, 65)'),dict(color='rgb(0, 128, 0)'),
                dict(classes=['green','red']),dict(visible=False),dict(classes=None)):
            with self.subTest(changes=changes):
                result=select_answer('提交答案: AB 得分: 2/2',evidence(**changes))
                self.assertEqual(result['status'],'missing');self.assertIsNone(result['answer'])
                self.assertEqual(result['reason_code'],'no_usable_correct_answer')

    def test_scores_are_not_an_answer_source(self):
        for value in ('1/1','10/10','2.50 / 2.5',None,'','1','1/1/1','1/2','NaN/NaN','0/0'):
            self.assertIsNone(select_answer('提交答案: AB',evidence(score=value))['answer'])

    def test_green_status_only_or_disagreement_never_becomes_letters(self):
        for changes in (dict(result_text='全对',submitted=None),dict(submitted=''),
                        dict(result_text='A',submitted='B'),dict(submitted='TRUE',result_text='TRUE')):
            self.assertIsNone(select_answer('提交答案: AB',evidence(**changes))['answer'])
        self.assertIsNone(select_answer('提交答案: A 得分: 1/1')['answer'])

    def test_empty_or_unrecognized_official_answer_stays_missing(self):
        for text in ('正确答案：','参考答案：暂不公布','提交答案: AB 得分: 2/2'):
            self.assertIsNone(select_answer(text,evidence())['answer'])

    def test_single_question_dom_error_is_missing_next_question_still_succeeds(self):
        for exception in (Error('Local fixture error'),RuntimeError('Local fixture unexpected error')):
            broken=Mock();broken.inner_text.side_effect=exception
            result=answer_for_item(broken)
            self.assertEqual(result['status'],'missing')
            self.assertEqual(result['reason_code'],'no_usable_correct_answer')
        good=Mock();good.inner_text.return_value='参考答案：AB'
        good.evaluate.return_value=evidence()
        self.assertEqual(answer_for_item(good)['answer'],'AB')
        good.evaluate.assert_not_called()
        submitted=Mock();submitted.inner_text.return_value='提交答案: AB 得分: 2/2'
        self.assertIsNone(answer_for_item(submitted)['answer'])
        submitted.evaluate.assert_not_called()

    def test_old_inferred_mapping_is_denied_even_with_green_full_evidence(self):
        sequence=[dict(resource_id='r',slide_id='s',page=1)]
        mapping=dict(sequence[0],occurrence=0,answer='AB',source='submission_verified',
            status='available',confidence='verified_submission',evidence=evidence())
        self.assertFalse(trusted_answer(mapping))
        with self.assertRaises(FileProblem):annotated_sources(['unused'],sequence,[mapping])
        self.assertGreater(ANNOTATION_VERSION,2)


if __name__=='__main__':unittest.main()
