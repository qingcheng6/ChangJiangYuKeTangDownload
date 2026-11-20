"""Grid acceptance with previously authorized, hash-verified real quiz images.

No fresh site requests; this is real-content offline acceptance, not a new
website extraction or an official-answer positive claim.
"""
import hashlib
import sys
from pathlib import Path
from threading import Event

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ykt.accounts import Accounts
from ykt.files import Manifest
from ykt.quiz_grid import normalize_layout
from ykt.quiz_pdf import merge_lesson,verified_pdf
from ykt.storage import read_json,write_json


def main():
    accounts=Accounts(ROOT,'https://changjiang.yuketang.cn')
    account=next(r for r in accounts.rows if r['legacy'])
    task=read_json(ROOT/'.local/v2_stage3/page_probe.json')['task']
    source=Manifest(ROOT/'.local/native_only/live_output',account['owner'],accounts.origin,layout='flat')
    lesson=next(iter(source.read_existing()['lessons'].values()))
    assert lesson['quiz_pages']==14
    originals={str(p):(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns)
        for p in source.root.rglob('*') if p.suffix.lower() in ('.jpg','.png','.pdf')}
    output=ROOT/'.local/grid/real_output'
    target=Manifest(output,account['owner'],accounts.origin,layout='flat')
    proof=dict(source='previously_authorized_real_images_offline',cases={})
    configs=[(orientation,count) for orientation in ('portrait','landscape') for count in (1,2,4,6,8,12)]
    for orientation,count in configs:
        spec=normalize_layout(dict(orientation=orientation,count=count))
        label=orientation+'_'+str(count)
        with target as m:result=merge_lesson(m,task,source,lesson,Event(),lambda _:None,grid=spec)
        assert result['status']=='complete',(label,result)
        assert result['question_count']==14 and result['pages']==(14+count-1)//count
        assert verified_pdf(target,result,grid=spec)
        proof['cases'][label]=dict(pages=result['pages'],questions=14,path=result['path'],
            raster_dimensions=[(p['width'],p['height']) for p in result['grid_page_checks']])
        write_json(ROOT/'.local/grid/real_verified.json',proof)
        print('REAL_CONTENT_GRID',label,'PASS',flush=True)
    spec=normalize_layout(dict(mode='custom',rows=2,columns=3))
    with target as m:marked=merge_lesson(m,task,source,lesson,Event(),lambda _:None,answers=True,grid=spec)
    assert marked['status']=='complete' and marked['annotated_pages']==0 and marked['missing_answers']==14
    assert verified_pdf(target,marked,answers=True,grid=spec)
    before=target.resolve(marked['path']).stat().st_mtime_ns
    with target as m:repeated=merge_lesson(m,task,source,lesson,Event(),lambda _:None,answers=True,grid=spec)
    assert repeated['skipped'] and target.resolve(marked['path']).stat().st_mtime_ns==before
    proof['cases']['custom_native_answers_repeat']=dict(pages=marked['pages'],path=marked['path'],
        annotated=0,missing=14,repeated_skipped=True)
    assert all((hashlib.sha256(Path(p).read_bytes()).hexdigest(),Path(p).stat().st_mtime_ns)==value
        for p,value in originals.items())
    assert not list(output.rglob('*.part')) and not list(output.rglob('*.png'))
    proof['originals_unchanged']=True
    write_json(ROOT/'.local/grid/real_verified.json',proof)
    print('REAL_CONTENT_GRID_ALL_PASS',flush=True)


if __name__=='__main__':main()
