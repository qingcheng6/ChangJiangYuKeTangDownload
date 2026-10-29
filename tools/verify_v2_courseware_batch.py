"""Real serial courseware acceptance; output is isolated from historical files."""
import sys,hashlib
from pathlib import Path
from queue import Empty
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ykt.accounts import Accounts
from ykt.storage import read_json,write_json
from ykt.files import Manifest
from ykt.courseware import verified_courseware
from ykt.worker import ScanWorker
from threading import Event
R=Path(__file__).resolve().parents[1];o='https://changjiang.yuketang.cn';a=Accounts(R,o);row=a.get(read_json(R/'.local/v2_stage1/gui_live.json')['new_account_id']);site=a.site_dir(row)
cache=read_json(site/'courses.json');historic=read_json(next((R/'.local/phase3_output/雨课堂习题下载').glob('任务清单_*.json')))
tasks=[]
for status in ('complete','no_images'):
 old=next(l for l in historic['lessons'].values() if l['status']==status);c=next(c for c in cache['courses'] if c['id']==old['course_id']);l=next(l for l in c['lessons'] if l['id']==old['lesson_id']);tasks.append(dict(course_id=c['id'],course_name=c['name'],lesson=l))
proof=dict(schema_version=1,cases={});base=R/'.local/v2_stage3/batch';base.mkdir(exist_ok=True)

def run(name,selected,options,folder=None,stop_on=None):
 directory=base/(folder or name);directory.mkdir(exist_ok=True)
 w=ScanWorker(o,site,account_id=row['id'],expected_owner=row['owner'],layout='v2');w.start_download(selected,directory,row['owner'],options)
 result=None;features=None;errors=[]
 while w.running or not w.events.empty():
  try:kind,data=w.events.get(timeout=.25)
  except Empty:continue
  if kind=='log':
   print(data,flush=True)
   if stop_on and stop_on in data:w.stop()
  elif kind=='download_result':result=data
  elif kind=='feature_progress':features=data
  elif kind in ('needs_human','error'):errors.append(data);w.stop()
 w.thread.join();assert result is not None and not errors,repr(errors)
 m=Manifest(directory,row['owner'],o,layout='v2');data=m.read_existing()
 complete=[l['courseware_pdf'] for l in data['lessons'].values() if l.get('courseware_pdf',{}).get('status')=='complete']
 assert all(verified_courseware(m,p,Event()) for p in complete)
 proof['cases'][name]=dict(result=result,features=features,pages=[p['pages'] for p in complete],part_files=len(list(directory.rglob('*.part'))))
 write_json(R/'.local/v2_stage3/batch_verified.json',proof);print('CASE_VERIFIED',name,flush=True)
 return m,data,result

only=dict(quiz_images=False,quiz_pdf=False,courseware_pdf=True)
m,d,result=run('serial',tasks,only)
assert result['success']==2 and result['failed']==0
assert proof['cases']['serial']['pages'][0]==44
before={p:(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns) for p in m.root.rglob('*.pdf')}
_,_,result=run('repeat',tasks,only,'serial')
assert all((hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns)==v for p,v in before.items())
key=tasks[0]['course_id']+':'+tasks[0]['lesson']['id']+':'+tasks[0]['lesson']['courseware_id']
p=m.resolve(d['lessons'][key]['courseware_pdf']['path']);(R/'.local/v2_stage3/own_corrupt_backup.pdf').write_bytes(p.read_bytes());p.write_bytes(p.read_bytes()[:100])
run('corrupt_recovery',[tasks[0]],only,'serial')
_,_,result=run('safe_stop',[tasks[0]],only,stop_on='已读取课件页 1/')
assert result['status']=='stopped'
_,_,result=run('stop_resume',[tasks[0]],only,'safe_stop')
assert result['success']==1
_,d,result=run('all_three',[tasks[1]],dict(quiz_images=True,quiz_pdf=True,courseware_pdf=True))
assert result['success']==1 and next(iter(d['lessons'].values()))['quiz_pdf']['status']=='no_images'
print('REAL_STAGE3_BATCH_PASSED',flush=True)
