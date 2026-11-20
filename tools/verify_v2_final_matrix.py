"""Seven real export combinations using one authorized lesson and isolated paths."""
import sys,hashlib
from pathlib import Path
from queue import Empty
from threading import Event
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ykt.accounts import Accounts
from ykt.storage import read_json,write_json
from ykt.worker import ScanWorker
from ykt.files import Manifest
from ykt.quiz_pdf import verified_pdf
from ykt.courseware import verified_courseware
from pypdf import PdfReader

def main():
 a=Accounts(ROOT,'https://changjiang.yuketang.cn');row=next(r for r in a.rows if r['legacy']) if '--legacy' in sys.argv else a.get(read_json(ROOT/'.local/v2_stage1/gui_live.json')['new_account_id']);layout='legacy' if row['legacy'] else 'v2';cache=read_json(a.site_dir(row)/'courses.json')
 task=read_json(ROOT/'.local/v2_stage3/page_probe.json')['task']
 course=next(c for c in cache['courses'] if c['id']==task['course_id']);task['lesson']=next(l for l in course['lessons'] if l['id']==task['lesson']['id'])
 base=ROOT/('.local/v2_stage4/matrix_legacy_final' if row['legacy'] else '.local/v2_stage4/matrix');base.mkdir(exist_ok=True);proof_file=ROOT/('.local/v2_stage4/matrix_legacy_verified.json' if row['legacy'] else '.local/v2_stage4/matrix_verified.json');proof=read_json(proof_file) if '--resume' in sys.argv and proof_file.exists() else dict(schema_version=1,cases={})
 expected=read_json(ROOT/'.local/v2_stage3/single_verified.json')['sequence']
 features=('quiz_images','quiz_pdf','courseware_pdf')
 def run(mask,repeat=False):
  options={f:bool(mask&(1<<i)) for i,f in enumerate(features)}
  selected=base/('mode_'+str(mask));selected.mkdir(exist_ok=True);directory=a.image_directory(row,selected)
  before={p:(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns) for p in directory.rglob('*') if p.suffix.lower() in ('.jpg','.pdf')}
  worker=ScanWorker(a.origin,a.site_dir(row),account_id=row['id'],expected_owner=row['owner'],layout=layout)
  assert worker.start_download([task],directory,row['owner'],options)
  result=None;counts=None;errors=[]
  while worker.running or not worker.events.empty():
   try:kind,data=worker.events.get(timeout=.25)
   except Empty:continue
   if kind=='download_result':result=data
   elif kind=='feature_progress':counts=data
   elif kind in ('error','needs_human'):errors.append(data);worker.stop()
  worker.thread.join();assert not errors and result and result['success']==1,(mask,errors,result)
  manifest=Manifest(directory,row['owner'],a.origin,layout=layout);lesson=next(iter(manifest.read_existing()['lessons'].values()))
  images=list(directory.rglob('*.jpg'));pdfs=list(directory.rglob('*.pdf'))
  assert len(images)==(14 if options['quiz_images'] else 0)
  assert len(pdfs)==int(options['quiz_pdf'])+int(options['courseware_pdf'])
  if options['quiz_images']:assert all(manifest.verified(r) for r in lesson['resources'].values())
  if options['quiz_pdf']:assert verified_pdf(manifest,lesson['quiz_pdf']) and lesson['quiz_pdf']['pages']==14
  if options['courseware_pdf']:
   meta=lesson['courseware_pdf'];assert verified_courseware(manifest,meta,Event()) and meta['pages']==44
   assert [s['page'] for s in meta['sequence']]==[s['page'] for s in expected]
   pdf=PdfReader(manifest.resolve(meta['path']))
   assert all(hashlib.sha256(p['/Resources']['/XObject']['/Im0'].get_object().get_data()).hexdigest()==s['sha256'] for p,s in zip(pdf.pages,expected))
  assert not list(directory.rglob('*.part'))
  if repeat:assert all((hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns)==state for p,state in before.items())
  assert all(counts[f]['success']==int(options[f]) and counts[f]['failed']==0 for f in features)
  proof['cases'][str(mask)+('_repeat' if repeat else '')]=dict(options=options,result=result,features=counts,images=len(images),pdfs=len(pdfs),mtime_unchanged=repeat,output_under_account_component=True if row['legacy'] else row['output_component'] in directory.parts)
  write_json(ROOT/('.local/v2_stage4/matrix_legacy_verified.json' if row['legacy'] else '.local/v2_stage4/matrix_verified.json'),proof);print('REAL_COMBINATION_VERIFIED',mask,'repeat',repeat,flush=True)
 for mask in range(1,8):
  if str(mask) not in proof['cases']:run(mask)
 for mask in range(1,8):
  if str(mask)+'_repeat' not in proof['cases']:run(mask,True)
 print('ALL_SEVEN_AND_REPEATS_PASSED',flush=True)
if __name__=='__main__':main()
