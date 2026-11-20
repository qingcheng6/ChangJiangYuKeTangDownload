"""Live double-check fallback acceptance; private output, original images protected."""
import hashlib
import sys
from pathlib import Path
from queue import Empty

from pypdf import PdfReader
from PIL import Image,ImageOps

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ykt.accounts import Accounts
from ykt.answer_images import trusted_answer
from ykt.files import Manifest
from ykt.quiz_pdf import verified_pdf
from ykt.storage import read_json,write_json
from ykt.worker import ScanWorker


def main():
    accounts=Accounts(ROOT,'https://changjiang.yuketang.cn')
    account=next(a for a in accounts.rows if a['legacy'])
    task=read_json(ROOT/'.local/v2_stage3/page_probe.json')['task']
    output=ROOT/'.local/answer_dual/live_output'
    expected=['D','ABC','A','B','A','ABC','B']+[None]*7
    def products():
        return {str(p.relative_to(output)):(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns)
            for p in output.rglob('*') if p.suffix in ('.jpg','.png','.pdf')}
    proof=dict(schema_version=1,source='live_browser',cases={})
    for label,marked,images in [('plain',False,True),('dual',True,True),('dual_repeat',True,True),('dual_pdf_only_repeat',True,False)]:
        before=products()
        worker=ScanWorker(accounts.origin,accounts.site_dir(account),account_id=account['id'],
            expected_owner=account['owner'],layout='flat')
        worker.start_download([task],output,account['owner'],
            dict(quiz_images=images,quiz_pdf=True,courseware_pdf=False,quiz_answers=marked))
        result=None;errors=[];logs=[]
        while worker.running or not worker.events.empty():
            try:kind,data=worker.events.get(timeout=.3)
            except Empty:continue
            if kind=='download_result':result=data
            elif kind=='log':logs.append(data)
            elif kind in ('error','needs_human'):errors.append(kind);worker.stop()
        worker.thread.join()
        assert result and result['success']==1 and not errors,(label,result,errors)
        manifest=Manifest(output,account['owner'],accounts.origin,layout='flat')
        lesson=next(iter(manifest.read_existing()['lessons'].values()))
        assert verified_pdf(manifest,lesson['quiz_pdf'])
        if marked:
            meta=lesson['quiz_pdf_answers']
            assert verified_pdf(manifest,meta,answers=True)
            assert [row['answer'] for row in meta['answer_mapping']]==expected
            assert meta['annotated_pages']==7 and meta['missing_answers']==7
            assert all(trusted_answer(row) for row in meta['answer_mapping'][:7])
            plain=PdfReader(manifest.resolve(lesson['quiz_pdf']['path']))
            marked_pdf=PdfReader(manifest.resolve(meta['path']))
            assert len(plain.pages)==len(marked_pdf.pages)==14
            for index,(p,m) in enumerate(zip(plain.pages,marked_pdf.pages)):
                record=lesson['resources'][lesson['pdf_sequence'][index]['resource_id']]
                raw=manifest.resolve(record['path']).read_bytes()
                # pypdf's JPEG extraction can re-encode its .image convenience
                # view. Check the actual embedded DCT bytes for untouched pages.
                plain_stream=p['/Resources']['/XObject']['/Im0'].get_object()
                marked_stream=m['/Resources']['/XObject']['/Im0'].get_object()
                assert plain_stream.get_data()==raw
                if expected[index]:
                    with Image.open(manifest.resolve(record['path'])) as source:
                        original=ImageOps.exif_transpose(source).convert('RGB')
                    annotated=m.images[0].image.convert('RGB')
                    assert annotated.crop((0,0,*original.size)).tobytes()==original.tobytes()
                    assert annotated.width==original.width and annotated.height>original.height
                else:assert marked_stream.get_data()==raw
            assert result['downloaded']==0
        after=products()
        assert all(after[p]==value for p,value in before.items())
        if label.endswith('repeat'):assert after==before
        assert not list(output.rglob('*.part'))
        proof['cases'][label]=dict(result=result,existing_products_unchanged=True,pages=14,
            annotated_pages=7 if marked else 0,per_page_original_pixels_unchanged=marked)
        if marked:proof['answer_mapping']=lesson['quiz_pdf_answers']['answer_mapping']
        write_json(ROOT/'.local/answer_dual/live_verified.json',proof)
        write_json(ROOT/'.local/answer_dual/last_logs.json',dict(logs=logs))
        print('LIVE_DUAL_ANSWER',label,'PASS',flush=True)


if __name__=='__main__':main()
