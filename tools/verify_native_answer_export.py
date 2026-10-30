"""Live negative answer acceptance; outputs stay in the private QA directory."""
import hashlib
import sys
from pathlib import Path
from queue import Empty

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ykt.accounts import Accounts
from ykt.files import Manifest
from ykt.quiz_pdf import verified_pdf
from ykt.storage import read_json,write_json
from ykt.worker import ScanWorker


def main():
    accounts=Accounts(ROOT,'https://changjiang.yuketang.cn')
    account=next(a for a in accounts.rows if a['legacy'])
    task=read_json(ROOT/'.local/v2_stage3/page_probe.json')['task']
    output=ROOT/'.local/native_only/live_output'
    def products():
        return {str(p.relative_to(output)):(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns)
            for p in output.rglob('*') if p.suffix in ('.jpg','.png','.pdf')}
    proof=dict(schema_version=1,source='live_browser',cases={})
    for label,marked in [('plain',False),('marked_missing',True),('marked_repeat',True)]:
        before=products()
        worker=ScanWorker(accounts.origin,accounts.site_dir(account),account_id=account['id'],
            expected_owner=account['owner'],layout='flat')
        worker.start_download([task],output,account['owner'],
            dict(quiz_images=True,quiz_pdf=True,courseware_pdf=False,quiz_answers=marked))
        result=None;errors=[]
        while worker.running or not worker.events.empty():
            try:kind,data=worker.events.get(timeout=.3)
            except Empty:continue
            if kind=='download_result':result=data
            elif kind in ('error','needs_human'):
                errors.append(kind);worker.stop()
        worker.thread.join()
        assert result and result['success']==1 and not errors,(label,result,errors)
        manifest=Manifest(output,account['owner'],accounts.origin,layout='flat')
        lesson=next(iter(manifest.read_existing()['lessons'].values()))
        assert verified_pdf(manifest,lesson['quiz_pdf'])
        if marked:
            metadata=lesson['quiz_pdf_answers']
            assert verified_pdf(manifest,metadata,answers=True)
            assert metadata['annotated_pages']==0 and metadata['missing_answers']==14
            assert all(row['answer'] is None for row in lesson['native_answers'])
            assert manifest.resolve(metadata['path']).read_bytes()==manifest.resolve(lesson['quiz_pdf']['path']).read_bytes()
        after=products()
        assert all(after[p]==value for p,value in before.items())
        if marked:assert result['downloaded']==0
        assert not list(output.rglob('*.part'))
        proof['cases'][label]=dict(result=result,existing_products_unchanged=True,
            pages=lesson['quiz_pdf']['pages'],annotated_pages=lesson.get('quiz_pdf_answers',{}).get('annotated_pages'))
        write_json(ROOT/'.local/native_only/live_verified.json',proof)
        print('LIVE_NATIVE_ANSWER',label,'PASS',flush=True)


if __name__=='__main__':main()
