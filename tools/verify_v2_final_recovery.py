"""Corrupt only this phase's own artifacts, then verify integrated recovery."""
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

def main():
 a=Accounts(ROOT,'https://changjiang.yuketang.cn');row=next(r for r in a.rows if r['legacy']) if '--legacy' in sys.argv else a.get(read_json(ROOT/'.local/v2_stage1/gui_live.json')['new_account_id']);layout='legacy' if row['legacy'] else 'v2'
 selected=ROOT/('.local/v2_stage4/matrix_legacy_final/mode_7' if row['legacy'] else '.local/v2_stage4/matrix/mode_7');directory=a.image_directory(row,selected);m=Manifest(directory,row['owner'],a.origin,layout=layout);data=m.read_existing();lesson=next(iter(data['lessons'].values()))
 image=m.resolve(next(iter(lesson['resources'].values()))['path']);pdfs=[m.resolve(lesson[f]['path']) for f in ('quiz_pdf','courseware_pdf')]
 others={p:(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns) for p in directory.rglob('*.jpg') if p!=image}
 backup=ROOT/('.local/v2_stage4/corruption_legacy_backup' if row['legacy'] else '.local/v2_stage4/corruption_backup');backup.mkdir(exist_ok=True)
 for i,p in enumerate([image]+pdfs):
  assert (ROOT/'.local/v2_stage4').resolve() in p.resolve().parents and m.root in p.parents
  saved=backup/(str(i)+p.suffix)
  expected=next(iter(lesson['resources'].values()))['sha256'] if i==0 else lesson['quiz_pdf' if i==1 else 'courseware_pdf']['sha256']
  if not saved.exists():
   assert hashlib.sha256(p.read_bytes()).hexdigest()==expected
   saved.write_bytes(p.read_bytes())
  assert hashlib.sha256(saved.read_bytes()).hexdigest()==expected
  p.write_bytes(p.read_bytes()[:100])
 task=read_json(ROOT/'.local/v2_stage3/page_probe.json')['task'];worker=ScanWorker(a.origin,a.site_dir(row),account_id=row['id'],expected_owner=row['owner'],layout=layout)
 worker.start_download([task],directory,row['owner'],dict(quiz_images=True,quiz_pdf=True,courseware_pdf=True));result=None;errors=[]
 while worker.running or not worker.events.empty():
  try:kind,value=worker.events.get(timeout=.25)
  except Empty:continue
  if kind=='download_result':result=value
  if kind in ('error','needs_human'):errors.append(value);worker.stop()
 worker.thread.join();assert result and not errors and result['success']==1 and result['downloaded']==1 and result['skipped']==13,(result,errors)
 lesson=next(iter(m.read_existing()['lessons'].values()))
 assert all(m.verified(r) for r in lesson['resources'].values())
 assert verified_pdf(m,lesson['quiz_pdf']) and verified_courseware(m,lesson['courseware_pdf'],Event())
 assert all((hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns)==state for p,state in others.items())
 assert all(p.read_bytes()==(backup/(str(i)+p.suffix)).read_bytes() for i,p in enumerate([image]+pdfs))
 write_json(ROOT/('.local/v2_stage4/recovery_legacy_verified.json' if row['legacy'] else '.local/v2_stage4/recovery_verified.json'),dict(schema_version=1,result=result,corrupted_artifacts=3,recovered_exact_bytes=True,other_13_images_unchanged=True,quiz_pdf_pages=lesson['quiz_pdf']['pages'],courseware_pdf_pages=lesson['courseware_pdf']['pages'],part_files=len(list(directory.rglob('*.part')))))
 print('INTEGRATED_CORRUPTION_RECOVERY_PASSED',flush=True)
if __name__=='__main__':main()
