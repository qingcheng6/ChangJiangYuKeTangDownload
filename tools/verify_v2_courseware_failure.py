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
 write_json(R/'.local/v2_stage3/failure_verified.json',proof);print('CASE_VERIFIED',name,flush=True)
 return m,data,result


only=dict(quiz_images=False,quiz_pdf=False,courseware_pdf=True)
fault=base/'local_pdf_conflict'
with Manifest(fault,row['owner'],o,layout='v2') as m:
 lesson=m.lesson(tasks[0]);lesson['status']='pdf_only'
 from ykt.quiz_pdf import pdf_path
 path=pdf_path(m,tasks[0],lesson,{},suffix='_课件.pdf')
 path.mkdir(parents=True)
 lesson['courseware_pdf']=dict(status='pending',path=str(path.relative_to(m.root)))
 m.save()
_,_,result=run('local_pdf_conflict',tasks,only,'local_pdf_conflict')
assert result['failed']==1 and result['success']==1
assert base.resolve() in path.resolve().parents and path.is_dir() and not list(path.iterdir())
path.rmdir()  # Only our exact empty test collision directory.
_,_,result=run('conflict_resume',tasks,only,'local_pdf_conflict')
assert result['success']==2
run('all_three_nonempty',[tasks[0]],dict(quiz_images=True,quiz_pdf=True,courseware_pdf=True))
print('REAL_FAILURE_CONTINUE_AND_COMBINED_PASSED',flush=True)
