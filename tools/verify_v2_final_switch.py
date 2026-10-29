"""Native-start scan, then GUI-controller switch between distinct platform owners."""
import sys,tkinter as tk
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ykt.accounts import Accounts
from ykt.gui import CourseApp
from ykt.storage import read_json,write_json

def main():
 a=Accounts(ROOT,'https://changjiang.yuketang.cn');known=read_json(ROOT/'.local/v2_stage4/second_account.json');old=a.get(known['previous_id']);new=a.get(known['account_id']);previous=a.get()
 root=tk.Tk();app=CourseApp(root,ROOT,account_id=old['id']);root.title('雨课堂 V2 最终扫描与双账号切换回归')
 # Keep one actual lesson selected while refreshing, then verify switch clears it.
 task=read_json(ROOT/'.local/v2_stage3/page_probe.json')['task'];app.toggle(app.lesson_iid((task['course_id'],task['lesson']['id'])))
 stage='waiting_native_start';proof=dict(schema_version=1,ticks=0,stages=[],new_cache_before=(a.site_dir(new)/'courses.json').read_bytes().hex())
 start=app.start_scan
 def tracked_start():
  started=start()
  if app.account['id']==new['id']:
   proof['switch_worker_started']=app.worker.running;app.stop()
  return started
 app.start_scan=tracked_start
 def observe():
  nonlocal stage
  proof['ticks']+=1
  if stage=='waiting_native_start' and app.worker.running:stage='scanning_old'
  if stage=='scanning_old' and app.waiting_human:
   proof['old_scan_requires_human']=True;stage='blocked';app.close()
  if stage=='scanning_old' and not app.worker.running and app.catalog and app.catalog['status']=='complete' and app.metrics['completed'].get()==len(app.catalog['courses']):
   proof['old_scan']=dict(owner=app.catalog['owner_fingerprint'],courses=len(app.catalog['courses']),lessons=sum(len(c['lessons']) for c in app.catalog['courses']),selected=len(app.selection.selected),metrics={k:v.get() for k,v in app.metrics.items()})
   assert proof['old_scan']['selected']==1
   old_worker=app.worker;app.switch_account(new['id'])
   proof['switch']=dict(old_worker_alive=old_worker.running,changed_worker=app.worker is not old_worker,
     owner=app.catalog.get('owner_fingerprint') if app.catalog else None,courses=len(app.catalog['courses']) if app.catalog else 0,
     selected=len(app.selection.selected),output_component=app.account['output_component'])
   stage='switch_stopping'
  elif stage=='switch_stopping' and not app.worker.running:
   assert proof['switch']['owner']==new['owner']!=old['owner']
   assert proof['switch']['selected']==0 and not proof['switch']['old_worker_alive']
   assert (a.site_dir(new)/'courses.json').read_bytes().hex()==proof['new_cache_before']
   proof['new_cache_not_overwritten_by_stop']=True;stage='complete';root.after(500,app.close)
  proof.update(stage=stage,ui_thread=app.ui_thread,worker_thread=app.worker.thread.ident if app.worker.thread else None,
   running=app.worker.running,callback_errors=app.callback_errors,status=app.status.get())
  # Do not store a second copy of the course cache inside the observation log.
  write_json(ROOT/'.local/v2_stage4/switch_verified.json',{k:v for k,v in proof.items() if k!='new_cache_before'})
  if stage!='complete':root.after(100,observe)
 root.after(100,observe)
 root.after(300000,app.close)
 try:root.mainloop()
 finally:
  a.activate(previous['id']);proof.update(closed=True,worker_alive_after_close=app.worker.running)
  write_json(ROOT/'.local/v2_stage4/switch_verified.json',{k:v for k,v in proof.items() if k!='new_cache_before'})
if __name__=='__main__':main()
