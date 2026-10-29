"""Real second-platform-account export and integrated stop/resume acceptance."""
import sys
from pathlib import Path
from queue import Empty
from threading import Event
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ykt.accounts import Accounts
from ykt.storage import read_json,write_json
from ykt.files import Manifest
from ykt.worker import ScanWorker
from ykt.quiz_pdf import verified_pdf
from ykt.courseware import verified_courseware

def main():
 a=Accounts(ROOT,'https://changjiang.yuketang.cn');known=read_json(ROOT/'.local/v2_stage4/second_account.json');second=a.get(known['account_id']);first=next(r for r in a.rows if r['legacy']) if '--legacy' in sys.argv else a.get(read_json(ROOT/'.local/v2_stage1/gui_live.json')['new_account_id'])
 old_task=read_json(ROOT/'.local/v2_stage3/page_probe.json')['task'];cache=read_json(a.site_dir(second)/'courses.json')
 choices=[(c,l) for c in cache['courses'] for l in c['lessons'] if l.get('is_finished') is True]
 choices.sort(key=lambda pair:(pair[0]['id']!=old_task['course_id'],pair[0]['name']!='工程经济学'))
 assert choices
 c,l=choices[0];new_task=dict(course_id=c['id'],course_name=c['name'],lesson=l)
 proof_path=ROOT/'.local/v2_stage4/additional_verified.json'
 proof=read_json(proof_path) if proof_path.exists() else dict(schema_version=1,cases={})
 def run(name,row,task,stop=False,folder=None):
  selected=ROOT/'.local/v2_stage4'/(folder or name);selected.mkdir(exist_ok=True);directory=a.image_directory(row,selected)
  layout='legacy' if row['legacy'] else 'v2'
  worker=ScanWorker(a.origin,a.site_dir(row),account_id=row['id'],expected_owner=row['owner'],layout=layout)
  worker.start_download([task],directory,row['owner'],dict(quiz_images=True,quiz_pdf=True,courseware_pdf=True))
  result=None;errors=[]
  while worker.running or not worker.events.empty():
   try:kind,data=worker.events.get(timeout=.25)
   except Empty:continue
   if kind=='log' and stop and '图片 1/' in data and '已保存' in data:worker.stop()
   if kind=='download_result':result=data
   if kind in ('error','needs_human'):errors.append(data);worker.stop()
  worker.thread.join();assert result and not errors,(name,result,errors)
  manifest=Manifest(directory,row['owner'],a.origin,layout=layout);lesson=next(iter(manifest.read_existing()['lessons'].values()))
  if not stop:
   assert result['success']==1,(name,result,lesson.get('error'),lesson.get('courseware_pdf'))
   if lesson.get('quiz_pdf',{}).get('status')=='complete':assert verified_pdf(manifest,lesson['quiz_pdf'])
   if lesson.get('courseware_pdf',{}).get('status')=='complete':assert verified_courseware(manifest,lesson['courseware_pdf'],Event())
   assert all(manifest.verified(r) for r in lesson['resources'].values() if r['status'] in ('complete','duplicate'))
  else:assert result['status']=='stopped' and 0<result['downloaded']<14
  assert not list(directory.rglob('*.part'))
  proof['cases'][name]=dict(result=result,owner_matches=manifest.read_existing()['owner']==row['owner'],layout=layout,account_component=True if row['legacy'] else row['output_component'] in directory.parts,
   images=len(list(directory.rglob('*.jpg'))),quiz_pdf_pages=lesson.get('quiz_pdf',{}).get('pages'),courseware_pdf_pages=lesson.get('courseware_pdf',{}).get('pages'))
  write_json(ROOT/'.local/v2_stage4/additional_verified.json',proof);print('ADDITIONAL_REAL_CASE',name,flush=True)
  return result
 if '--stop-only' not in sys.argv:
  run('second_account_export_repeat' if '--repeat-case' in sys.argv else 'second_account_export',second,new_task,
      folder='second_account_export' if '--repeat-case' in sys.argv else None)
 if '--second-only' in sys.argv:
  print('SECOND_ACCOUNT_EXPORT_PASSED',flush=True);return
 stopped=run('integrated_stop',first,old_task,True)
 resumed=run('integrated_resume',first,old_task,folder='integrated_stop')
 assert resumed['downloaded']+stopped['downloaded']==14 and resumed['skipped']==stopped['downloaded']
 print('INTEGRATED_STOP_PASSED' if '--stop-only' in sys.argv else 'SECOND_ACCOUNT_AND_INTEGRATED_STOP_PASSED',flush=True)
if __name__=='__main__':main()
