"""Local rendering/mapping fixtures, not a claim of live answer extraction."""
import io
import tempfile
import unittest
from pathlib import Path
from threading import Event

from PIL import Image
from pypdf import PdfReader
from ykt.answer_images import annotate_bytes, annotated_sources, normalize_choice, read_native_answer
from ykt.files import FileProblem
from ykt.quiz_pdf import validate_pdf, write_pdf


class AnswerImageTests(unittest.TestCase):
    def jpeg(self, color='white'):
        buffer=io.BytesIO()
        Image.new('RGB',(640,480),color).save(buffer,'JPEG')
        return buffer.getvalue()

    def test_letter_normalization_does_not_infer_from_scores_or_status(self):
        self.assertEqual(normalize_choice('Ａ，B / C A'),'ABC')
        for text in (None,'','全对','得分:1/1','提交答案: D','TRUE','A1','答案：B'):
            self.assertIsNone(normalize_choice(text))

    def test_only_explicit_correct_reference_labels_are_allowed(self):
        self.assertEqual(read_native_answer('正确答案：A')['answer'],'A')
        self.assertEqual(read_native_answer('参考答案：Ａ、B C')['answer'],'ABC')
        self.assertIsNone(read_native_answer('提交答案: D 得分: 1/1')['answer'])
        self.assertIsNone(read_native_answer('全对 得分: 2/2')['answer'])
        self.assertIsNone(read_native_answer('正确答案：A\n参考答案：B')['answer'])
        self.assertIsNone(read_native_answer('正确答案：')['answer'])

    def test_added_corner_band_preserves_every_original_pixel(self):
        for color in ('white','black','navy'):
            data=self.jpeg(color)
            marked=annotate_bytes(data,'ABC')
            with Image.open(io.BytesIO(data)) as original,Image.open(io.BytesIO(marked)) as result:
                self.assertEqual(result.width,original.width)
                self.assertGreater(result.height,original.height)
                self.assertEqual(result.crop((0,0,*original.size)).tobytes(),original.tobytes())
                colors=result.crop((0,original.height,result.width,result.height)).getdata()
                self.assertTrue(any(min(pixel)>240 for pixel in colors))
                self.assertTrue(any(max(pixel)<80 for pixel in colors))

    def test_missing_answer_keeps_original_encoded_bytes(self):
        data=self.jpeg()
        self.assertEqual(annotate_bytes(data,None),data)
        self.assertEqual(annotate_bytes(data,'全对'),data)

    def test_occurrence_mapping_can_mark_same_image_with_different_answers(self):
        with tempfile.TemporaryDirectory(prefix='native_answer_test_') as directory:
            root=Path(directory);source=root/'original.jpg';source.write_bytes(self.jpeg('navy'))
            original=(source.read_bytes(),source.stat().st_mtime_ns)
            sequence=[dict(resource_id='same',slide_id=str(i),page=i+1) for i in range(3)]
            mappings=[dict(row,occurrence=i,answer=a,source='correct_dom',status='available' if a else 'missing')
                      for i,(row,a) in enumerate(zip(sequence,('A','B',None)))]
            paths,identity,stats=annotated_sources([source]*3,sequence,mappings)
            self.assertEqual(stats,dict(annotated_pages=2,missing_answers=1))
            target=root/'answers.pdf';write_pdf(target,paths,Event())
            self.assertTrue(validate_pdf(target,3))
            pages=PdfReader(target).pages
            streams=[p['/Resources']['/XObject']['/Im0'].get_object().get_data() for p in pages]
            self.assertNotEqual(streams[0],streams[1])
            self.assertEqual(streams[2],original[0])
            self.assertEqual((source.read_bytes(),source.stat().st_mtime_ns),original)
            self.assertEqual({p.name for p in root.iterdir()},{'original.jpg','answers.pdf'})
            mappings[1]['slide_id']='0'
            with self.assertRaises(FileProblem):annotated_sources([source]*3,sequence,mappings)


if __name__=='__main__':unittest.main()
