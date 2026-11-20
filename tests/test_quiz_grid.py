"""Local grid/pixel/resume fixtures; never represent synthetic answers as live."""
import gc
import hashlib
import io
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from PIL import Image
from pypdf import PdfReader
from ykt.browser import Stopped
from ykt.downloader import _atomic_image
from ykt.files import Manifest,image_info
from ykt.gui import CourseApp
from ykt.quiz_grid import (normalize_layout,field_for,layout_suffix,placements,page_size,
                           geometry,GridPage,write_grid_pdf,validate_grid_pdf)
from ykt.quiz_pdf import merge_lesson,verified_pdf
from ykt.recovery import unfinished
from ykt.worker import ScanWorker

ORIGIN='https://changjiang.yuketang.cn';OWNER='a'*64


class GridTests(unittest.TestCase):
    def setUp(self):
        gc.collect()
        self.temp=tempfile.TemporaryDirectory(prefix='ykt_grid_');self.root=Path(self.temp.name)
        self.task=dict(course_id='1',course_name='课程',lesson=dict(id='2',courseware_id='3',name='课时'))
        self.source=Manifest(self.root/'source',OWNER,ORIGIN,layout='flat')
        self.colors=[(210,10,10),(10,170,10),(10,10,210),(200,150,10),(150,10,150),(10,150,150),(90,90,90)]
        with self.source as m:
            lesson=m.lesson(self.task);sequence=[]
            for i,color in enumerate(self.colors):
                buf=io.BytesIO();Image.new('RGB',(64,48),color).save(buf,'PNG');data=buf.getvalue()
                rid=hashlib.sha256(str(i).encode()).hexdigest();record=dict(resource_id=rid,status='pending')
                lesson['resources'][rid]=record;info=image_info(data)
                path=m.output_path(self.task,lesson,record,info,i+1,rid)
                _atomic_image(m,path,record,data,Event());record.update(info,status='complete')
                sequence.append(dict(resource_id=rid,slide_id=str(i),page=i+1))
            lesson.update(status='complete',warnings=[],quiz_pages=7,pdf_sequence=sequence)
            lesson['native_answers']=[dict(s,occurrence=i,answer='AB' if i==0 else None,source='correct_dom',
                status='available' if i==0 else 'missing') for i,s in enumerate(sequence)]
            m.save()
        self.lesson=self.source.read_existing()['lessons']['1:2:3']
        self.target=Manifest(self.root/'output',OWNER,ORIGIN,layout='flat')

    def tearDown(self):self.temp.cleanup()

    def merge(self,spec,answers=False):
        with self.target as m:
            return merge_lesson(m,self.task,self.source,self.lesson,Event(),lambda _:None,answers=answers,grid=spec)

    def test_all_presets_match_requested_orientation_table(self):
        table={1:(1,1),2:(2,1),4:(2,2),6:(3,2),8:(4,2),12:(4,3)}
        for count,(r,c) in table.items():
            for orientation,expected in [('portrait',(r,c)),('landscape',(c,r))]:
                spec=normalize_layout(dict(count=count,orientation=orientation))
                self.assertEqual((spec['rows'],spec['columns']),expected)
                boxes=placements(spec,[(64,48)]*count)
                w,h,margin,*_=geometry(spec)
                self.assertTrue(all(x>=margin-.001 and y>=margin-.001 and x+bw<=w-margin+.001 and y+bh<=h-margin+.001
                                    for x,y,bw,bh in boxes))

    def test_custom_positive_validation_and_unique_names(self):
        a=normalize_layout(dict(mode='custom',rows='2',columns='3'))
        b=normalize_layout(dict(mode='custom',rows='3',columns='2'))
        self.assertNotEqual(field_for(dict(quiz_layout=a)),field_for(dict(quiz_layout=b)))
        self.assertEqual(layout_suffix(a),'_竖版6题每页_2行3列')
        self.assertEqual(layout_suffix(b),'_竖版6题每页_3行2列')
        for value in ('0','-1','1.5','','abc',True,'9'*5000):
            with self.assertRaises(ValueError):normalize_layout(dict(mode='custom',rows=value,columns=2))
        with self.assertRaises(ValueError):normalize_layout(dict(mode='custom',rows=1000,columns=1000))

    def test_row_major_order_full_page_and_centered_short_page_pixels(self):
        spec=normalize_layout(dict(count=6));result=self.merge(spec)
        self.assertEqual(result['status'],'complete');self.assertEqual(result['pages'],2)
        self.assertEqual([r['questions'] for r in result['grid_page_checks']],[6,1])
        reader=PdfReader(self.target.resolve(result['path']))
        first=reader.pages[0].images[0].image.convert('RGB')
        for i,(x,y,w,h) in enumerate(placements(spec,[(64,48)]*6)):
            # Independent expected six-up row/column locations, rather than
            # sampling the same placement coordinates used by the renderer.
            row,column=divmod(i,2)
            px=round(first.width*(.25+.5*column));py=round(first.height*((1+2*row)/6))
            self.assertEqual(first.getpixel((px,py)),self.colors[i])
            self.assertAlmostEqual(w/h,64/48)
        last=reader.pages[1].images[0].image.convert('RGB')
        self.assertEqual(last.getpixel((last.width//2,last.height//2)),self.colors[-1])
        self.assertEqual(last.getpixel((last.width//2,100)),(255,255,255))
        self.assertTrue(verified_pdf(self.target,result,grid=spec))

    def test_default_legacy_and_new_single_question_paths_coexist(self):
        old=self.merge(None);path=self.target.resolve(old['path']);before=(path.read_bytes(),path.stat().st_mtime_ns)
        spec=normalize_layout({});new=self.merge(spec)
        self.assertTrue(new['path'].endswith('_竖版1题每页.pdf'))
        self.assertNotEqual(old['path'],new['path'])
        self.assertEqual((path.read_bytes(),path.stat().st_mtime_ns),before)
        self.assertEqual(new['pages'],7)

    def test_configurations_answers_and_custom_shapes_are_independent(self):
        variants=[]
        for raw,answers in [(dict(count=6),False),(dict(count=6,orientation='landscape'),False),
                (dict(mode='custom',rows=2,columns=3),True),(dict(mode='custom',rows=3,columns=2),True)]:
            spec=normalize_layout(raw);result=self.merge(spec,answers)
            self.assertEqual(result['status'],'complete');self.assertEqual(result['pages'],2)
            self.assertTrue(verified_pdf(self.target,result,answers=answers,grid=spec))
            self.assertFalse(verified_pdf(self.target,result,answers=answers))
            variants.append(result['path'])
            if answers:
                self.assertEqual(result['annotated_pages'],1);self.assertEqual(result['missing_answers'],6)
                self.assertIn('_带答案_竖版6题每页_',result['path'])
        self.assertEqual(len(set(variants)),4)
        self.assertFalse(list((self.root/'output').rglob('*.png')))

    def test_repeat_corruption_and_partial_sources_preserve_valid_outputs(self):
        spec=normalize_layout(dict(count=4));r=self.merge(spec);path=self.target.resolve(r['path']);before=path.read_bytes()
        with patch('ykt.quiz_pdf.write_grid_pdf',side_effect=AssertionError('Must skip valid grid')):
            self.assertTrue(self.merge(spec)['skipped'])
        path.write_bytes(before[:10]);self.assertFalse(verified_pdf(self.target,r,grid=spec))
        self.assertEqual(self.merge(spec)['status'],'complete');self.assertEqual(path.read_bytes(),before)
        self.lesson['status']='partial';self.assertEqual(self.merge(spec)['status'],'failed')
        self.assertEqual(path.read_bytes(),before)
        rows=unfinished(self.root/'output',OWNER,ORIGIN,layout='flat',features=['quiz_pdf'],quiz_layout=spec)
        self.assertEqual(len(rows),1)
        self.assertFalse(unfinished(self.root/'output',OWNER,ORIGIN,layout='flat',features=['quiz_pdf'],quiz_layout=normalize_layout(dict(count=2))))

    def test_stop_and_no_images_leave_no_parts_or_empty_output_folders(self):
        spec=normalize_layout(dict(count=6))
        with patch.object(GridPage,'read_bytes',side_effect=Stopped):
            with self.assertRaises(Stopped):self.merge(spec)
        self.assertFalse(list((self.root/'output').rglob('*.part')))
        self.assertEqual(self.merge(spec)['status'],'complete')
        fresh=normalize_layout(dict(count=8));self.lesson.update(status='no_images',quiz_pages=0)
        self.assertEqual(self.merge(fresh)['status'],'no_images')
        self.assertFalse(list((self.root/'output').rglob('*8题每页.pdf')))
        self.assertFalse(list((self.root/'output').rglob('习题图片')))

    def test_pixel_budget_rejects_instead_of_silently_downsampling(self):
        with patch('ykt.quiz_grid.MAX_PAGE_PIXELS',1000):
            result=self.merge(normalize_layout(dict(count=12)))
        self.assertEqual(result['status'],'failed')
        self.assertIn('减少行列数',result['error'])
        self.assertFalse(list((self.root/'output').rglob('*.pdf')))

    def test_high_resolution_page_validates_without_changing_global_decode_limit(self):
        import pypdf.filters
        from types import SimpleNamespace
        buffer=io.BytesIO();Image.new('RGB',(1280,960),'navy').save(buffer,'PNG')
        source=SimpleNamespace(read_bytes=lambda:buffer.getvalue())
        limit=pypdf.filters.ZLIB_MAX_OUTPUT_LENGTH
        spec=normalize_layout(dict(count=12));path=self.root/'high_resolution.pdf'
        _,checks=write_grid_pdf(path,[source]*12,Event(),spec)
        self.assertGreater(checks[0]['width']*checks[0]['height']*3,limit)
        self.assertTrue(validate_grid_pdf(path,1,spec,checks))
        self.assertEqual(pypdf.filters.ZLIB_MAX_OUTPUT_LENGTH,limit)
        checks[0]['encoded_sha256']='0'*64
        self.assertFalse(validate_grid_pdf(path,1,spec,checks))

    def test_transparency_is_composited_in_memory_and_logged(self):
        from types import SimpleNamespace
        buffer=io.BytesIO();Image.new('RGBA',(64,48),(255,0,0,128)).save(buffer,'PNG')
        original=buffer.getvalue();source=SimpleNamespace(read_bytes=lambda:original)
        checks,notes=[],[];spec=normalize_layout({})
        data=GridPage([source],spec,Event(),checks,notes).read_bytes()
        with Image.open(io.BytesIO(data)) as rendered:
            self.assertEqual(rendered.getpixel((rendered.width//2,rendered.height//2)),(255,127,127))
        self.assertTrue(any('透明通道合成白底' in line for line in notes))
        self.assertEqual(source.read_bytes(),original)

    def test_unexpected_page_groups_are_never_committed(self):
        spec = normalize_layout(dict(count=4))
        previous = self.merge(spec)
        path = self.target.resolve(previous['path'])
        original = path.read_bytes()
        # Force regeneration, and simulate a writer reporting incorrect groups
        # even though the overall page and question counts are both correct.
        def wrong_groups(temporary, *_):
            temporary.write_bytes(original)
            return [], [dict(questions=3), dict(questions=4)]

        with patch('ykt.quiz_pdf.verified_pdf', return_value=False), \
                patch('ykt.quiz_pdf.write_grid_pdf', side_effect=wrong_groups), \
                patch.object(Event, 'wait', return_value=False):
            result = self.merge(spec)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('实际习题分页与所选网格不符', result['error'])
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(list(path.parent.glob('*.part')))

    def test_invalid_worker_settings_do_not_start_browser_thread(self):
        worker=ScanWorker(ORIGIN,self.root/'site',account_id='local',expected_owner=OWNER)
        self.assertFalse(worker.start_download([self.task],self.root/'out',OWNER,
            dict(quiz_pdf=True,quiz_layout=dict(mode='custom',rows=0,columns=2))))
        self.assertFalse(worker.running)

    def test_z_gui_defaults_custom_visibility_and_invalid_input(self):
        project=self.root/'project';(project/'.local/changjiang.yuketang.cn').mkdir(parents=True)
        window=tk.Tk();window.withdraw()
        app=None
        try:
            app=CourseApp(window,project)
            self.assertEqual(app.paper_orientation.get(),'portrait')
            self.assertEqual(app.grid_choice.get(),'单题一页')
            self.assertEqual(app._grid_request()['count'],1)
            self.assertFalse(app.grid_custom.winfo_manager())
            app.grid_choice.set('自定义行列');app._grid_changed()
            self.assertEqual(app.grid_custom.winfo_manager(),'pack')
            app.grid_rows.set('0');app.export_quiz_pdf.set(True);app.start_download()
            self.assertIn('正整数',app.status.get());self.assertFalse(app.worker.running)
            app.grid_rows.set('3');app.grid_columns.set('2')
            self.assertEqual(app._grid_request()['count'],6)
            app.grid_choice.set('每页4张');app._grid_changed()
            self.assertFalse(app.grid_custom.winfo_manager())
            self.assertEqual(app.callback_errors,[])
        finally:
            window.destroy();del app,window;gc.collect()


if __name__=='__main__':unittest.main()
